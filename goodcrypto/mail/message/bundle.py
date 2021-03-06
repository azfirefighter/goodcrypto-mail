#! /usr/bin/python3
'''
    Copyright 2014-2016 GoodCrypto
    Last modified: 2016-11-03

    This file is open source, licensed under GPLv3 <http://www.gnu.org/licenses/>.
'''
import os, sys
from base64 import b64encode
from datetime import datetime, timedelta
from email.encoders import encode_base64
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from random import random
from time import sleep

# set up django early
from goodcrypto.utils import gc_django
gc_django.setup()

from django.utils.timezone import utc

from goodcrypto.constants import WARNING_WARNING_WARNING_TESTING_ONLY_DO_NOT_SHIP
from goodcrypto.mail import contacts, options
from goodcrypto.mail.constants import TAG_ERROR
from goodcrypto.mail.crypto_software import get_classname
from goodcrypto.mail.internal_settings import get_date_queue_last_active, get_domain, set_date_queue_last_active
from goodcrypto.mail.message import constants, history, utils
from goodcrypto.mail.message.crypto_message import CryptoMessage
from goodcrypto.mail.message.email_message import EmailMessage
from goodcrypto.mail.message.encrypt_utils import add_dkim_sig_optionally, create_protected_message
from goodcrypto.mail.message.inspect_utils import get_charset
from goodcrypto.mail.message.metadata import get_metadata_address, parse_bundled_message
from goodcrypto.mail.utils import send_message
from goodcrypto.mail.utils.notices import report_unable_to_send_bundled_messages
from goodcrypto.mail.utils.dirs import get_packet_directory, SafeDirPermissions
from goodcrypto.mail.utils.notices import report_bad_bundled_encrypted_message
from goodcrypto.oce.crypto_factory import CryptoFactory
from goodcrypto.oce.open_pgp_analyzer import OpenPGPAnalyzer
from goodcrypto.utils import i18n, get_email
from goodcrypto.utils.log_file import LogFile
from syr import mime_constants
from syr.exception import record_exception
from syr.python import is_string

class Bundle(object):
    '''
        Bundle and pad messages to each domain we have their metadata address.

        Unlike much of GoodCrypto, the results of many functions in this class are
        python style email.Messages, not EmailMessages or CryptoMessages.
        Comments try to use camel back to make the disticion clear (i.e., Message
        referrs to an email.Message().
    '''

    def __init__(self):
        '''
            >>> bundle = Bundle()
            >>> bundle is not None
            True
        '''
        self.DEBUGGING = False

        self.log = None

        self.bundled_messages = []
        self.crypted_with = []

    def ready_to_run(self):
        ''' Check to see if it's time to run the bundle and again. '''

        if options.encrypt_metadata() and options.bundle_and_pad():

            if options.bundle_frequency() == options.bundle_hourly():
                if WARNING_WARNING_WARNING_TESTING_ONLY_DO_NOT_SHIP:
                    frequency = timedelta(minutes=10)
                else:
                    frequency = timedelta(hours=1)
            elif options.bundle_frequency() == options.bundle_daily():
                frequency = timedelta(days=1)
            elif options.bundle_frequency() == options.bundle_weekly():
                frequency = timedelta(weeks=1)
            else:
                frequency = timedelta(hour=1)

            next_run = get_date_queue_last_active() + frequency

            ready = next_run <= datetime.utcnow()
            if not ready:
                self.log_message('bundle and pad messages next: {}'.format(next_run))

        else:
            self.log_message('not padding and packetizing messages')
            ready = False

        return ready

    def bundle_and_pad_messages(self):
        ''' Bundle and pad messages. '''

        try:
            self.log_message('starting to bundle and pad messages')
            self.bundle_and_pad()
            set_date_queue_last_active(datetime.utcnow())
            ok = True
            self.log_message('finished bundling and padding messages')
        except Exception as exception:
            ok = False
            report_unable_to_send_bundled_messages(exception)
            self.log_message('EXCEPTION - see syr.exception.log for details')

        return ok

    def bundle_and_pad(self):
        ''' Bundle and pad messages to reduce tracking. '''

        packet_dir = get_packet_directory()
        dirnames = os.listdir(packet_dir)
        if dirnames is None or len(dirnames) <= 0:
            self.log_message('no pending packets')
        else:
            self.log_message('starting to bundle and pad packets')
            for dirname in dirnames:
                # reset variables used per domain
                self.bundled_messages = []
                self.crypted_with = []

                path = os.path.join(packet_dir, dirname)
                if os.path.isdir(path) and dirname.startswith('.'):
                    to_domain = dirname[1:]
                    message = self.create_message(path, to_domain)
                    if message is None:
                        self.log_message('no message to send to {}'.format(to_domain))
                    elif self.send_bundled_message(message, to_domain):
                        self.add_history_and_remove(to_domain)
            self.log_message('finished bundling and paddding packets')

    def send_bundled_message(self, message, to_domain):
        ''' Send a Message to the domain. '''

        try:
            if message is None:
                result_ok = False
                self.log_message('nothing to send to {}'.format(to_domain))
            else:
                sender = get_email(get_metadata_address(domain=get_domain()))
                recipient = get_email(get_metadata_address(domain=to_domain))
                self.log_message('starting to send message from {} to {}'.format(sender, recipient))
                result_ok = send_message(sender, recipient, message.as_string())
                self.log_message('finished sending message')
        except Exception as exception:
            result_ok = False
            self.log_message('error while sending message')
            self.log_message('EXCEPTION - see syr.exception.log for details')
            record_exception()

        return result_ok

    def create_message(self, dirname, to_domain):
        ''' Create a Message to send that contains any other messages that are ready. '''

        inner_message = self.create_inner_message(dirname, to_domain)
        if inner_message is None:
            encrypted_message = None
            self.log_message('no inner message for {}'.format(to_domain))
        else:
            encrypted_message = self.create_encrypted_message(inner_message, to_domain)

        return encrypted_message

    def create_encrypted_message(self, inner_message, to_domain):
        ''' Create an encrypted Message. '''

        message = None

        if to_domain is None:
            self.log_message('domain is not defined')
        elif inner_message is None:
            self.log_message('no inner message defined')
        else:
            from_user = get_email(get_metadata_address(domain=get_domain()))
            to_user = get_email(get_metadata_address(domain=to_domain))

            crypto_message = create_protected_message(
                from_user, to_user, inner_message.as_string(), utils.get_message_id())
            if crypto_message.is_crypted():

                # add the DKIM signature to the inner message if user opted for it
                crypto_message = add_dkim_sig_optionally(crypto_message)

                message = crypto_message.get_email_message().get_message()
                self.crypted_with = crypto_message.get_metadata_crypted_with()
                self.log_message('crypted with: {}'.format(self.crypted_with))
                for part in message.walk():
                    self.log_message('Content type of part: {}'.format(part.get_content_type()))
                    if self.DEBUGGING: self.log_message(part.get_payload())
            else:
                report_bad_bundled_encrypted_message(to_domain, self.bundled_messages)

        return message

    def create_inner_message(self, dirname, to_domain):
        ''' Create a Message that contains other messages plus padding. '''

        message = None

        if dirname is None:
            self.log_message('no dir name defined in create_inner_message')
        elif to_domain is None:
            self.log_message('domain is not defined in create_inner_message')
        elif not os.path.exists(dirname):
            self.log_message('{} does not exist'.format(dirname))
        else:
            parts = []
            filenames = os.listdir(dirname)
            if filenames is None or len(filenames) <= 0:
                self.log_message('no pending messages for {}'.format(to_domain))
            else:
                estimated_size = 0
                # it's imporant to process in sorted order so larger messages don't get stuck
                # because smaller ones filled up the queue before the larger ones could be processed
                for filename in sorted(filenames):
                    part, filesize = self.get_mime_part(dirname, filename, estimated_size)
                    if part is not None:
                        parts.append(part)
                        estimated_size += filesize
                        self.bundled_messages.append(os.path.join(dirname, filename))
                self.log_message('bundling {} messages for {}'.format(len(parts), to_domain))

            parts = self.pad_message(parts, to_domain)
            if len(parts) > 0:
                boundary = 'Part{}{}--'.format(random(), random())
                params = {mime_constants.PROTOCOL_KEYWORD:mime_constants.MULTIPART_MIXED_TYPE,
                          mime_constants.CHARSET_KEYWORD:constants.DEFAULT_CHAR_SET,}
                message = self.prep_message_header(
                  MIMEMultipart(mime_constants.MIXED_SUB_TYPE, boundary, parts, **params), to_domain)
                if self.DEBUGGING: self.log_message('message: {}'.format(str(message)))
                for part in message.walk():
                    self.log_message('Content type: {}'.format(part.get_content_type()))
                    if self.DEBUGGING: self.log_message(part.get_payload())
            else:
                self.log_message('Unable to get any parts so no inner message created')

        return message

    def pad_message(self, parts, to_domain):
        ''' Pad the Message with random characters. '''

        # determine how large the bundled messages are
        original_size = 0
        for part in parts:
            original_size += len(part.as_string())

        # then pad the message with random characters
        current_size = original_size
        target_size = options.bundled_message_max_size()
        while current_size < target_size:
            # using urandom because it's less likely to lock up
            # a messaging program can't afford the potential locks up of /dev/random
            with open('/dev/urandom', 'rb') as rnd:
                rnd_bytes = rnd.read(target_size - current_size)
                if len(rnd_bytes) > target_size - current_size:
                    rnd_bytes = rnd_bytes[:target_size - current_size]
            part = MIMEApplication(
              b64encode(rnd_bytes), mime_constants.ALTERNATIVE_SUB_TYPE, encode_base64)
            current_size += len(part.as_string())
            parts.append(part)

        padded_bytes = target_size - original_size
        if padded_bytes < 0:
            self.log_message('original size: {}'.format(original_size))
            self.log_message('target size: {}'.format(target_size))
        self.log_message('padded with {} random bytes'.format(padded_bytes))

        return parts

    def get_mime_part(self, dirname, filename, estimated_size):
        ''' Get a MIME part with the Message.

            If any errors occur, then bounce the message to the original sender.
        '''
        part = None

        fullname = os.path.join(dirname, filename)
        filesize = os.stat(fullname).st_size
        max_size = options.bundled_message_max_size()

        # only look at the message files that won't make the overall size too large
        if (filename.startswith(constants.MESSAGE_PREFIX) and
            filename.endswith(constants.MESSAGE_SUFFIX)):

            # if the message is too large, then bounce it back to the user
            if filesize > max_size:
                self.bounce_message(fullname,
                  i18n('Message too large to send. It must be {size} KB or smaller'.format(
                         size=options.bundle_message_kb())))
                self.log_message('{} message too large; max size: {} KB'.format(
                    filesize, options.bundle_message_kb()))

            elif (filesize + estimated_size) < max_size:
                try:
                    with open(fullname, 'rb') as input_file:
                        content = input_file.read()
                        if content.endswith(constants.END_ADDENDUM.encode()):
                            part = MIMEApplication(
                             b64encode(content), mime_constants.ALTERNATIVE_SUB_TYPE, encode_base64)
                            if self.DEBUGGING: self.log_message('message part:\n{}'.format(part))
                        else:
                            self.log_message('{} is not ready to send'.format(filename))
                except:
                    record_exception()
                    self.log_message('EXCEPTION - see syr.exception.log for details')

            else:
                self.log_message('{} is too large for this batch of messages (estimated size with this message: {})'.format(filename, filesize + estimated_size))

        return part, filesize

    def prep_message_header(self, message, to_domain):
        ''' Prepare the header of a Message. '''

        if message is None:
            self.log_message('no message defined in prep_message_header')
        elif to_domain is None:
            self.log_message('domain is not defined in prep_message_header')
        else:
            message_date = datetime.utcnow().replace(tzinfo=utc)
            from_user = get_metadata_address(domain=get_domain())
            to_user = get_metadata_address(domain=to_domain)

            message.__setitem__(mime_constants.FROM_KEYWORD, from_user)
            message.__setitem__(mime_constants.TO_KEYWORD, to_user)
            message.__setitem__(constants.ORIGINAL_FROM, from_user)
            message.__setitem__(constants.ORIGINAL_TO, to_user)
            message.__setitem__(mime_constants.DATE_KEYWORD, message_date.__str__())
            message.__setitem__(mime_constants.MESSAGE_ID_KEYWORD, utils.get_message_id())
            self.log_message("message's content type: {}".format(message.get_content_type()))
            self.log_message("message's boundary: {}".format(message.get_boundary()))
            if self.DEBUGGING:
                self.log_message("message's key/value pair")
                for key in message.keys():
                    self.log_message('{}: {}'.format(key, message.get(key)))

        return message

    def add_history_and_remove(self, to_domain):
        ''' Add history records for the messages sent and then remove the associated file. '''

        def get_addendum_value(addendum, keyword):
            value = addendum[keyword]
            if is_string(value):
                value = value.strip()
            if value == 'True':
                value = True
            elif value == 'False':
                value = False

            return value

        if len(self.bundled_messages) > 0:
            for bundled_message in self.bundled_messages:
                self.log_message('message included in bundled: {}'.format(bundled_message))
                with open(bundled_message) as f:
                    original_message, addendum = parse_bundled_message(f.read())
                    self.log_message('addendum: {}'.format(addendum))
                    encrypted = get_addendum_value(addendum, constants.CRYPTED_KEYWORD)
                    private_signed = get_addendum_value(addendum, constants.PRIVATE_SIGNED_KEYWORD)
                    clear_signed = get_addendum_value(addendum, constants.CLEAR_SIGNED_KEYWORD)
                    dkim_signed = get_addendum_value(addendum, constants.DKIM_SIGNED_KEYWORD)
                    if encrypted or private_signed or clear_signed or dkim_signed:
                        sender = get_addendum_value(addendum, mime_constants.FROM_KEYWORD)
                        recipient = get_addendum_value(addendum, mime_constants.TO_KEYWORD)
                        verification_code = get_addendum_value(addendum, constants.VERIFICATION_KEYWORD)
                        crypto_message = CryptoMessage(email_message=EmailMessage(original_message))
                        crypto_message.set_smtp_sender(sender)
                        crypto_message.set_smtp_recipient(recipient)
                        crypto_message.set_crypted(encrypted)
                        crypto_message.set_crypted_with(addendum[constants.CRYPTED_WITH_KEYWORD])
                        crypto_message.set_metadata_crypted(True)
                        crypto_message.set_metadata_crypted_with(self.crypted_with)
                        crypto_message.set_private_signed(private_signed)
                        if private_signed:
                            if encrypted:
                                crypto_message.add_private_signer({
                                 constants.SIGNER: sender, constants.SIGNER_VERIFIED: True})
                            crypto_message.add_private_signer({
                             constants.SIGNER: get_metadata_address(sender), constants.SIGNER_VERIFIED: True})
                        crypto_message.set_clear_signed(clear_signed)
                        if clear_signed:
                            if encrypted:
                                crypto_message.add_clear_signer({
                                 constants.SIGNER: sender, constants.SIGNER_VERIFIED: True})
                            else:
                                crypto_message.add_clear_signer({
                                 constants.SIGNER: get_metadata_address(sender), constants.SIGNER_VERIFIED: True})
                        crypto_message.set_dkim_signed(dkim_signed)
                        if dkim_signed:
                            crypto_message.set_dkim_sig_verified(True)
                        history.add_outbound_record(crypto_message, verification_code)
                        self.log_message('added outbound history record from {}'.format(sender))
                        if self.DEBUGGING:
                            self.log_message('logged headers in goodcrypto.message.utils.log')
                            utils.log_message_headers(crypto_message, tag='bundled headers')

                if os.path.exists(bundled_message):
                    os.remove(bundled_message)
                else:
                    self.log_message('tried to delete message after bundling it, but message no longer exists on disk')
        else:
            self.log_message('no bundled messages')

    def bounce_message(self, fullname, error_message):
        ''' Bounce a Message to the original user. '''

        notified_user = False

        if fullname is not None and os.path.exists(fullname):
            with open(fullname) as f:
                content = f.read()
                original_message, addendum = parse_bundled_message(content)
                subject = i18n('{} - Unable to send message to {email}'.format(
                    TAG_ERROR, email=addendum[mime_constants.TO_KEYWORD]))
                notified_user = utils.bounce_message(
                    original_message, addendum[mime_constants.FROM_KEYWORD], subject, error_message)
                self.log_message(subject)

        return notified_user

    def log_message(self, message):
        '''
            Log the message to the local log.
        '''
        if self.log is None:
            self.log = LogFile()

        self.log.write_and_flush(message)

def main():
    # sleep is measured in seconds
    if WARNING_WARNING_WARNING_TESTING_ONLY_DO_NOT_SHIP:
        PERIOD = 10 * 60
    else:
        PERIOD = 60 * 60

    while True:
        try:
            bundle = Bundle()
            if bundle.ready_to_run():
                bundle.bundle_and_pad_messages()
        except Exception as exception:
            report_unable_to_send_bundled_messages(exception)
            print(str(exception))

        sleep(PERIOD)

if __name__ == "__main__":

    print()
    print('GoodCrypto Padding and Packetization')
    print('Copyright 2015-2016 GoodCrypto.com')
    main()

