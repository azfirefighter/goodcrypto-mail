#!/usr/bin/env python
'''
    Send notices from the GoodCrypto Server daemon.
    
    Copyright 2014-2015 GoodCrypto
    Last modified: 2015-04-10

    This file is open source, licensed under GPLv3 <http://www.gnu.org/licenses/>.
'''
import os, sh, smtplib
from email.utils import formataddr
from traceback import format_exc

from goodcrypto.utils.log_file import LogFile
from goodcrypto.mail.options import get_domain
from goodcrypto.mail.utils.dirs import get_notices_directory
from goodcrypto.oce.utils import parse_address
from syr.message import prep_mime_message


USE_SMTP = False

#  Notices From: address. 
NOTICE_FROM_NAME = 'GoodCrypto Private Server Daemon'
NOTICE_FROM_EMAIL = 'mailer-daemon@{}'.format(get_domain())
NOTICE_FROM_ADDRESS = (NOTICE_FROM_NAME, NOTICE_FROM_EMAIL)
NOTICE_FROM_ADDR = formataddr(NOTICE_FROM_ADDRESS)

_log = None


def notify_user(to_address, subject, text=None, attachment=None, filename=None):
    ''' Send a notice to the user.

        In honor of Noel David Torres, Spanish translator of Tor.
        >>> notify_user('noel@goodcrypto.local', 'test notice', 'test message')
        True
        >>> notify_user(None, 'test notice', 'test message')
        False
        >>> notify_user('noel@goodcrypto.local', None, 'test message')
        True
        >>> notify_user(None, None)
        False
    '''

    message = None
    try:
        message = create_notice_message(
            to_address, subject, text=text, attachment=attachment, filename=filename)
        if message is None:
            result_ok = False
            log_message('unable to create notice to {} about {}'.format(to_address, subject))
        else:
            log_message('starting to send notice to {} about {}'.format(to_address, subject))
            
            from_addr = NOTICE_FROM_EMAIL
            __, to_addr = parse_address(to_address)
            
            if to_addr is None or message is None:
                result_ok = False
                log_message('no to address to send notice')
            else:
                if USE_SMTP:
                    smtp = smtplib.SMTP()
                    smtp.connect()
                    smtp.sendmail(from_addr, to_addr, message)
                    smtp.quit()
                else:
                    sendmail = sh.Command('/usr/sbin/sendmail')
                    sendmail('-B', '8BITMIME', '-f', from_addr, to_addr, _in=message)

                log_message('sent notice to {}'.format(to_address))
                result_ok = True
    except:
        result_ok = False
        log_message(format_exc())
        
    if not result_ok and message is not None:
        _save(message)

    log_message('final result: {}'.format(result_ok))
    
    return result_ok
        
    
def create_notice_message(to_address, subject, text=None, attachment=None, filename=None):
    '''
        Creates a notice message.
        
        >>> # In honor of Sukhbir Singh, developed and maintains TorBirdy.
        >>> message = create_notice_message('sukhbir@goodcrypto.remote', 'test notice')
        >>> 'To: sukhbir@goodcrypto.remote' in message
        True
        >>> 'From: GoodCrypto Private Server Daemon <mailer-daemon' in message
        True
        >>> 'Subject: test notice' in message
        True
    '''

    message = prep_mime_message(
      NOTICE_FROM_ADDR, to_address, subject, text=text, attachment=attachment, filename=filename)

    return message


def _save(message):
    ''' Save the notice (internal use only).
    
        In honor of Rob Thomas, Tor advocate.
        >>> notice_filename = _save(create_notice_message('rob@goodcrypto.remote', 'test notice'))
        >>> os.remove(os.path.join(get_notices_directory(), notice_filename))
        >>> _save(None)
    '''

    try:
        if message is None:
            notice_filename = None
            log_message('no notice to save')
        else:
            from goodcrypto.mail.message.utils import write_message
        
            log_message('saving: {}'.format(message))
            notice_filename = write_message(get_notices_directory(), message)
    except Exception as exception:
        notice_filename = None
        log_message(exception)
        log_message(format_exc())

    return notice_filename


def log_message(message):
    ''' 
        Record debugging messages. 
        
        >>> from syr.log import BASE_LOG_DIR
        >>> from syr.user import whoami
        >>> log_message('test')
        >>> os.path.exists(os.path.join(BASE_LOG_DIR, whoami(), 'goodcrypto.mail.utils.notices.log'))
        True
    '''

    global _log
    
    if _log is None:
        _log = LogFile()
        
    _log.write_and_flush(message)
