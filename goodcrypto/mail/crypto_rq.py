'''
    Manage crypto via RQ.

    Copyright 2015 GoodCrypto
    Last modified: 2015-11-22

    This file is open source, licensed under GPLv3 <http://www.gnu.org/licenses/>.
'''
import os, pickle
from base64 import b64decode, b64encode
from redis import Redis
from rq import Connection, Queue
from rq.job import Job

# set up django early
from goodcrypto.utils import gc_django
gc_django.setup()

from goodcrypto.mail.rq_crypto_settings import CRYPTO_RQ, CRYPTO_REDIS_PORT
from goodcrypto.utils.constants import REDIS_HOST
from goodcrypto.utils.exception import record_exception
from goodcrypto.utils.log_file import LogFile
from goodcrypto.utils.manage_rq import get_job_count, get_job_results



_log = None


def add_private_key_via_rq(contacts_encryption):
    '''
        Start the process of adding a private key.
        If one exists, then verify the info in the database matches.
    '''
    try:
        if contacts_encryption is None:
            result = False
            log_message("cannot add private key without a contact's encryption record")
        else:
            from goodcrypto.mail.sync_db_with_keyring import sync_private_key

            email = contacts_encryption.contact.email
            result = add_contacts_crypto_to_rq(contacts_encryption, sync_private_key)
            log_message("queued sync of private key for {}".format(email, result))

    except Exception as exception:
        record_exception()
        log_message('EXCEPTION - see goodcrypto.utils.exception.log for details')
        result = False

    return result

def set_fingerprint_via_rq(contacts_encryption):
    '''
        Start the process of setting a fingerprint if there's a matching key in the database.
    '''

    try:
        if contacts_encryption is None:
            result = False
            log_message("cannot set the fingerprint without a contact's encryption")
        else:
            from goodcrypto.mail.sync_db_with_keyring import sync_fingerprint

            email = contacts_encryption.contact.email
            result = add_contacts_crypto_to_rq(contacts_encryption, sync_fingerprint)
            log_message('queued syncing fingerprint for {}: {}'.format(email, result))
    except Exception as exception:
        result = False
        record_exception()
        log_message('EXCEPTION - see goodcrypto.utils.exception.log for details')

    return result

def delete_contacts_crypto_via_rq(contacts_encryption):
    '''
        Delete the key(s) for the contact's encryption.
    '''

    try:
        if contacts_encryption is None:
            result = False
            log_message("cannot delete contact's encryption because it is not defined")
        else:
            from goodcrypto.mail.sync_db_with_keyring import sync_deletion

            email = contacts_encryption.contact.email
            result = add_contacts_crypto_to_rq(contacts_encryption, sync_deletion)
            log_message("queued delete key for {}: {}".format(email, result))
    except Exception as exception:
        result = False
        record_exception()
        log_message('EXCEPTION - see goodcrypto.utils.exception.log for details')

    return result

def add_contacts_crypto_to_rq(contacts_encryption, function):
    '''
        Add a job with the contact's encryption to the crypto RQ.
    '''

    result_ok = False
    try:
        if contacts_encryption is None or function is None:
            log_message('missing key data: {} contacts_encryption; {} function'.format(
                contacts_encryption, str(function)))
            result_ok = False

        else:
            ONE_MINUTE = 60 #  one minute, in seconds
            DEFAULT_TIMEOUT = 10 * ONE_MINUTE

            crypto_jobs = get_job_count(CRYPTO_RQ, CRYPTO_REDIS_PORT)
            redis_connection = Redis(REDIS_HOST, CRYPTO_REDIS_PORT)
            queue = Queue(name=CRYPTO_RQ, connection=redis_connection, async=True)
            secs_to_wait = DEFAULT_TIMEOUT * (queue.count + crypto_jobs + 1)
            job = queue.enqueue_call(function,
                                     args=[b64encode(pickle.dumps(contacts_encryption))],
                                     timeout=secs_to_wait)

            result_ok = get_job_results(queue, job, secs_to_wait, contacts_encryption.contact.email)
            if job.is_failed:
                result_ok = False
                log_message('job failed for {}'.format(email))
    except Exception as exception:
        result_ok = False
        record_exception()
        log_message('EXCEPTION - see goodcrypto.utils.exception.log for details')

    return result_ok

def prep_action(contacts_crypto):
    ''' Prepare a crypto action. '''

    result_ok = True
    crypto_name = email = key_plugin = None
    try:
        if contacts_crypto is None:
            result_ok = False
            log_message('contacts crypto not defined')
        else:
            crypto_name = contacts_crypto.encryption_software.name
            email = contacts_crypto.contact.email

            crypto_record = crypto_software.get(contacts_crypto.encryption_software)
            if crypto_record is None:
                result_ok = False
                log_message('{} encryption not defined in database'.format(crypto_name))
            elif not crypto_record.active:
                result_ok = False
                log_message('{} encryption is not active'.format(crypto_name))
            else:
                key_plugin = KeyFactory.get_crypto(
                    crypto_name, crypto_software.get_key_classname(crypto_name))
                result_ok = key_plugin is not None
                if not result_ok:
                    log_message('key plugin not defined'.format(crypto_name))
    except:
        record_exception()
        log_message('EXCEPTION - see goodcrypto.utils.exception.log for details')
        result_ok = False

    return result_ok, crypto_name, email, key_plugin

def log_message(message):
    '''
        Log a message to the local log.

        >>> import os.path
        >>> from syr.log import BASE_LOG_DIR
        >>> from syr.user import whoami
        >>> log_message('test')
        >>> os.path.exists(os.path.join(BASE_LOG_DIR, whoami(), 'goodcrypto.mail.crypto_rq.log'))
        True
    '''

    global _log

    if _log is None:
        _log = LogFile()

    _log.write_and_flush(message)
