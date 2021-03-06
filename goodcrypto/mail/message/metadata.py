'''
    Copyright 2015-2016 GoodCrypto
    Last modified: 2016-08-03

    This file is open source, licensed under GPLv3 <http://www.gnu.org/licenses/>.
'''
import os
from datetime import datetime

from goodcrypto.mail import contacts, options, user_keys
from goodcrypto.mail.constants import AUTO_GENERATED, MESSAGE_HEADER
from goodcrypto.mail.internal_settings import get_domain
from goodcrypto.mail.message import constants
from goodcrypto.mail.message.inspect_utils import get_charset
from goodcrypto.mail.message.message_exception import MessageException
from goodcrypto.mail.utils import get_domain_user, parse_domain
from goodcrypto.mail.utils.dirs import get_packet_directory, SafeDirPermissions
from goodcrypto.oce.crypto_factory import CryptoFactory
from goodcrypto.utils import get_email, i18n
from goodcrypto.utils.log_file import LogFile
from syr import mime_constants
from syr.exception import record_exception
from syr.fs import get_unique_filename
from syr.message import prep_mime_message


DEBUGGING = False

_log = None


def get_metadata_address(email=None, domain=None):
    '''
        Get the metadata email address for this user's email address or domain.

        >>> metadata_address = get_metadata_address(None)
        >>> metadata_address is None
        True
    '''

    metadata_address = None

    if email is not None:
        try:
            domain = parse_domain(email)
        except:
            record_exception()
            log_message('EXCEPTION - see syr.exception.log for details')

    if domain is None or len(domain.strip()) <= 0:
        log_message('unable to get metadata address without a domain')
    else:
        try:
            metadata_address = '{} domain key (system use only) <{}@{}>'.format(domain, get_domain_user(), domain)
        except:
            record_exception()
            log_message('EXCEPTION - see syr.exception.log for details')

    return metadata_address

def is_metadata_address(email):
    '''
        Determine if the email address is a metadata address.

        >>> is_metadata_address(None)
        False
    '''
    result = False

    if email is None:
        log_message('email not defined so not a metadata address')
    else:
        try:
            address = get_email(email)
            local, __, __ = address.partition('@')
            if local == get_domain_user():
                result = True
        except:
            log_message('unable to partition: {} ({})'.format(email, address))
            record_exception()
            log_message('EXCEPTION - see syr.exception.log for details')

    return result

def get_metadata_user_details(email, encryption_name):
    '''
        Get the metadata address and key for the encryption program.

        >>> get_metadata_user_details(None, None)
        (False, None, None)
    '''

    metadata_address = fingerprint = None
    ok = False

    try:
        metadata_address = get_metadata_address(email=email)
        fingerprint, verified, active = contacts.get_fingerprint(metadata_address, encryption_name)
        if fingerprint is None:
            from goodcrypto.mail.message.utils import sync_fingerprint_via_queue

            ok = False
            log_message('no fingerprint for {}'.format(metadata_address))
            # queue up to get the fingerprint
            sync_fingerprint_via_queue(contacts.get_contacts_crypto(email, encryption_name=encryption_name))
        elif not active:
            ok = False
            log_message('{}  is not active'.format(metadata_address))
        elif options.require_key_verified() and not verified:
            ok = False
            log_message('{}  is not verified and verification required'.format(metadata_address))
        else:
            ok = True
    except:
        ok = False
        record_exception()
        log_message('EXCEPTION - see syr.exception.log for details')

    if not ok:
        metadata_address = None

    return ok, metadata_address, fingerprint

def get_from_metadata_user_details(email, encryption_name):
    '''
        Get the metadata address and key for the encryption program.

        >>> get_from_metadata_user_details(None, None)
        (False, None, None)
    '''

    metadata_address = passcode = None
    ok = False

    try:
        ok, metadata_address, fingerprint = get_metadata_user_details(email, encryption_name)
        if ok:
            passcode = user_keys.get_passcode(metadata_address, encryption_name)
            if passcode is None:
                ok = False
                log_message('no user key for {}'.format(metadata_address))
            else:
                ok = True
                log_message('ready to protect metadata using {}'.format(encryption_name))

        elif fingerprint is None:
            log_message('adding {}'.format(encryption_name, email))
            contacts.add(email, encryption_name, source=MESSAGE_HEADER)
    except:
        ok = False
        record_exception()
        log_message('EXCEPTION - see syr.exception.log for details')

    if not ok:
        metadata_address = passcode = None

    return ok, metadata_address, passcode

def prep_metadata_key_message(from_user, to_user):
    '''
        Prepare a Message that contains notice about a new metadata key.
    '''
    def get_extra_headers():

        from goodcrypto.mail.message.utils import make_public_key_block

        extra_headers = None

        key_block = make_public_key_block(local_metadata_address)
        if len(key_block) > 0:
            extra_headers = []
            for line in key_block:
                name, __, value = line.partition(': ')
                extra_headers.append((name, value))
            extra_headers.append((constants.ACCEPTED_CRYPTO_SOFTWARE_HEADER, ','.join(encryption_software)))

        return extra_headers

    try:
        from goodcrypto.mail.message.utils import add_private_key

        message = local_metadata_address = remote_metadata_address = None
        if from_user is None or to_user is None:
            log_message('missing user data so unable to prepare metadata key message')

        else:
            # we want to send a message from the original recipient's "no metadata" address
            # to the original sender's "no metadata" address
            remote_metadata_address = get_metadata_address(email=from_user)
            local_metadata_address = get_metadata_address(email=to_user)
            encryption_software = contacts.get_encryption_names(local_metadata_address)

            extra_headers = get_extra_headers()
            if extra_headers is None:
                log_message('"no metadata" key is not ready yet')
                for encryption_name in encryption_software:
                    add_private_key(local_metadata_address, encryption_name)
                    log_message('adding a "no metadata" {} key'.format(encryption_name))
            else:
                log_message('preparing a "no metadata" key message')
                # the message should only contain the key in the header
                message = prep_mime_message(
                           local_metadata_address, remote_metadata_address, 'Message',
                           text='', extra_headers=extra_headers)
    except:
        message = None
        record_exception()
        log_message('EXCEPTION - see syr.exception.log for details')

    return message, local_metadata_address, remote_metadata_address

def send_metadata_key(from_user, to_user):
    '''
        Send the local user's metadata key to the sender's metadata address in a new message.
    '''
    try:
        if from_user is None or to_user is None:
            sent_message = False
            log_message('missing user data so message not sent to admin')

        else:
            from goodcrypto.mail.utils import send_message

            # it doesn't matter whether the local system wants their users' metadata protected, we want the
            # recipient's system to have the metadata key so they can protect the recipient's metadata
            log_message('preparing to send "no metadata" key')

            message, local_metadata_address, remote_metadata_address = prep_metadata_key_message(
                from_user, to_user)
            send_message(local_metadata_address, remote_metadata_address, message)

            sent_message = True
            log_message('sent "no metadata" address to {}'.format(from_user))
    except:
        sent_message = False
        record_exception()
        log_message('EXCEPTION - see syr.exception.log for details')

    return sent_message

def is_ready_to_protect_metadata(from_user, to_user):
    '''
        Determine if encrypt_metadata is True and we have a
        metadata key for both the sender's and recipient's servers.
    '''
    if from_user is None or to_user is None:
        ready = False
    else:
        ready = options.encrypt_metadata()
        log_message("options set to encrypt metadata: {}".format(ready))
        if ready:
            # first see if we know the metadata address for the recipient's server
            to_metadata_user = get_metadata_address(email=to_user)
            encryption_names = contacts.get_encryption_names(to_metadata_user)
            ready = len(encryption_names) > 0
            log_message("{} uses {} encryption programs".format(to_metadata_user, encryption_names))
            for encryption_name in encryption_names:
                ready, __, __ = get_metadata_user_details(
                    to_user, encryption_name)

                # we only need 1 valid metadata address
                if ready:
                    log_message("recipient's server ready to protect metadata")
                    break

        if ready:
            # then see if we know the metadata address for the sender's server
            from_metadata_user = get_metadata_address(email=from_user)
            encryption_names = contacts.get_encryption_names(from_metadata_user)
            ready = len(encryption_names) > 0
            log_message("{} uses {} encryption programs".format(from_metadata_user, encryption_names))
            for encryption_name in encryption_names:
                ready, __, fingerprint = get_from_metadata_user_details(
                    from_user, encryption_name)

                # we only need 1 valid metadata address
                if ready:
                    log_message("sender's server ready to protect metadata")
                    break
                elif fingerprint is None:
                    contacts_crypto = contacts.get_contacts_crypto(from_user, encryption_name=encryption_name)
                    if contacts_crypto is None:
                        # we'll automatically add a private key after creating the contact's crypto
                        contacts.add(from_user, encryption_name, source=AUTO_GENERATED)
                        contacts_crypto = contacts.get_contacts_crypto(
                            from_user, encryption_name=encryption_name)
                    else:
                        user_key = user_keys.get(from_user, encryption_name)
                        if user_key is None:
                            from goodcrypto.mail.message.utils import sync_private_key_via_queue

                            sync_private_key_via_queue(contacts_crypto)
                            log_message('started to add private {} key for {}'.format(
                                encryption_name, from_user))
                        else:
                            from goodcrypto.mail.message.utils import sync_fingerprint_via_queue

                            sync_fingerprint_via_queue(contacts_crypto)
                            log_message('started to update {} fingerprint for {}'.format(
                                encryption_name, from_user))

    log_message('ready to protect metadata: {}'.format(ready))

    return ready

def packetize(crypto_message, encrypted_with, verification_code):
    ''' Packetize for later delivery. '''

    try:
        message_name = None
        domain = parse_domain(crypto_message.smtp_recipient())
        dirname = os.path.join(get_packet_directory(), '.{}'.format(domain))
        if not os.path.exists(dirname):
            os.mkdir(dirname, SafeDirPermissions)
            log_message('created packet queue for {}'.format(domain))
        crypto_message.set_processed(True)

        encrypted_names = ''
        if crypto_message.is_crypted():
            for encrypted_name in encrypted_with:
                if len(encrypted_names) > 0:
                    encrypted_names += ', '
                encrypted_names += encrypted_name
            log_message('queued message encrypted with: {}'.format(encrypted_names))
        message_name = get_unique_filename(dirname, constants.MESSAGE_PREFIX, constants.MESSAGE_SUFFIX)
        with open(message_name, 'wt') as f:
            f.write(crypto_message.get_email_message().to_string())
            f.write('{}'.format(constants.START_ADDENDUM))
            f.write('{}: {}\n'.format(mime_constants.FROM_KEYWORD, crypto_message.smtp_sender()))
            f.write('{}: {}\n'.format(mime_constants.TO_KEYWORD, crypto_message.smtp_recipient()))
            f.write('{}: {}\n'.format(constants.CRYPTED_KEYWORD, crypto_message.is_crypted()))
            f.write('{}: {}\n'.format(constants.CRYPTED_WITH_KEYWORD, encrypted_names))
            f.write('{}: {}\n'.format(constants.PRIVATE_SIGNED_KEYWORD, crypto_message.is_private_signed()))
            f.write('{}: {}\n'.format(constants.CLEAR_SIGNED_KEYWORD, crypto_message.is_clear_signed()))
            f.write('{}: {}\n'.format(constants.DKIM_SIGNED_KEYWORD, crypto_message.is_dkim_signed()))
            f.write('{}: {}\n'.format(constants.VERIFICATION_KEYWORD, verification_code))
            f.write('{}'.format(constants.END_ADDENDUM))
        log_message('packetized message filename: {}'.format(os.path.basename(message_name)))
    except:
        message_name = None
        crypto_message.set_processed(False)
        error_message = i18n('Unable to packetize message due to an unexpected error.')
        log_message(error_message)
        log_message('EXCEPTION - see syr.exception.log for details')
        record_exception()
        raise MessageException(value=error_message)

    return message_name

def parse_bundled_message(bundled_message_bytes):
    '''
        Parse a message that was bundled.

        Test extreme cases.
        >>> message, addendum = parse_bundled_message(None)
        >>> message is None
        True
        >>> addendum[mime_constants.FROM_KEYWORD] is None
        True
    '''

    def set_addendum_item(msg, keyword, boolean_type=False):
        try:
            i = msg.find(keyword)
            if i > 0:
                item = msg[i + len(keyword + ': '):]
                i = item.find('\n')
                if boolean_type:
                    addendum[keyword] = item[:i] == 'True'
                else:
                    addendum[keyword] = item[:i]
        except:
            record_exception()
            addendum[keyword] = None


    addendum = {
       mime_constants.FROM_KEYWORD: None,
       mime_constants.TO_KEYWORD: None,
       constants.CRYPTED_KEYWORD: False,
       constants.CRYPTED_WITH_KEYWORD: [],
       constants.PRIVATE_SIGNED_KEYWORD: False,
       constants.CLEAR_SIGNED_KEYWORD: False,
       constants.DKIM_SIGNED_KEYWORD: False,
       constants.VERIFICATION_KEYWORD: None,
    }
    original_message = sender = recipient = crypted_with = msg = None
    crypted = False
    try:
        if isinstance(bundled_message_bytes, str):
            bundled_message = bundled_message_bytes
        else:
            bundled_message = bundled_message_bytes.decode()

        log_message('{}'.format(bundled_message)) #DEBUG
        # separate the original message from the addendum
        i = bundled_message.find(constants.START_ADDENDUM)
        if i > 0:
            msg = bundled_message[i:]
            original_message = bundled_message[:i]

        set_addendum_item(msg, mime_constants.FROM_KEYWORD)
        set_addendum_item(msg, mime_constants.TO_KEYWORD)
        set_addendum_item(msg, constants.CRYPTED_KEYWORD, boolean_type=True)

        # get the programs the message used to encrypt
        i = msg.find(constants.CRYPTED_WITH_KEYWORD)
        if i > 0:
            crypted_with = msg[i + len(constants.CRYPTED_WITH_KEYWORD + ': '):]
            i = crypted_with.find('\n')
            addendum[constants.CRYPTED_WITH_KEYWORD] = crypted_with[:i].split(', ')

        # get details about the signatures
        set_addendum_item(msg, constants.PRIVATE_SIGNED_KEYWORD, boolean_type=True)
        set_addendum_item(msg, constants.CLEAR_SIGNED_KEYWORD, boolean_type=True)
        set_addendum_item(msg, constants.DKIM_SIGNED_KEYWORD, boolean_type=True)

        # get the verification code that was added to the message if it was encrypted
        i = msg.find(constants.VERIFICATION_KEYWORD)
        if i > 0:
            verification_code = msg[i + len(constants.VERIFICATION_KEYWORD + ': '):]
            i = verification_code.find('\n')
            addendum[constants.VERIFICATION_KEYWORD] = verification_code[:i].split(', ')

        if DEBUGGING: log_message('addendum:\n{}'.format(addendum))
    except AttributeError as attribute_exception:
        # common error for "padding" parts of a bundled message
        log_message(attribute_exception)
    except UnboundLocalError as unbound_exception:
        # common error for "padding" parts of a bundled message
        log_message(unbound_exception)
    except UnicodeDecodeError as unicode_decode_error:
        # common error for "padding" parts of a bundled message
        log_message(unicode_decode_error)
    except:
        record_exception()
        log_message('EXCEPTION - see syr.exception.log for details')

    return original_message, addendum

def log_message(message):
    '''
        Log a message.

        >>> import os
        >>> from syr.log import BASE_LOG_DIR
        >>> from syr.user import whoami
        >>> log_message('test')
        >>> os.path.exists(os.path.join(BASE_LOG_DIR, whoami(), 'goodcrypto.mail.message.metadata.log'))
        True
    '''
    global _log

    if _log is None:
        _log = LogFile()

    _log.write_and_flush(message)

