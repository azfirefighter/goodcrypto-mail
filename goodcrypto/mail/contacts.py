#!/usr/bin/env python
'''
    Copyright 2014 GoodCrypto.
    Last modified: 2014-10-23

    This file is open source, licensed under GPLv3 <http://www.gnu.org/licenses/>.

    Manage email addresses that use encryption. 

    If you want to get a list of contacts known to GoodCrypto,
    then you could use the following code:
    <pre>
        contacts = Contacts()
        contact_list = contacts.get_contact_list()
    </pre>

    If you instead only want to get a list of contacts
    that are configured to use a particular encryption program,
    then replace the last line of the above example with:
    <pre>
        contact_list = contacts.get_contact_list(cryptoProgram)
    </pre>

    If you want to get more details about a specific
    address, then you could replace the last line
    with the following code:
    <pre>
    contact = contacts.get(email)
    if contact is not None:
        user_name = contact.user_name
        email = contact.email
    </pre>
'''
from traceback import format_exc
from django.db.models.query import QuerySet

from goodcrypto.mail import crypto_software, international_strings
from goodcrypto.mail.models import Contact, ContactsCrypto
from goodcrypto.utils.log_file import LogFile
from goodcrypto.oce.crypto_exception import CryptoException
from goodcrypto.oce.key.key_factory import KeyFactory
from goodcrypto.oce.utils import parse_address


_log = None

def is_ok():
    '''
        Determine if all contacts have all the required fields.

        See the unittest to understand how to really use this function
        >>> ok = is_ok()
    '''

    result_ok = True
    try:
        contacts = Contact.objects.all()
        if contacts is None or len(contacts) <= 0:
            result_ok = False
            log_message('no contacts defined')
        else:
            for contact in contacts:
                if result_ok:
                    result_ok = len(contact.email) > 0
                else:
                    break
    except Exception:
        result_ok = False
        log_message(format_exc())

    return result_ok


def exists(email):
    '''
        Determine if the contact exists already.

        Test an unknown email address so we're sure of the result.
        See the unittest to understand how to really use this function.
        
        >>> # In honor of Thomas Tamm, who was a whistleblower to the NY Times about senior
        >>> # Justice officials fight against the widening scope of warrantless NSA surveillance.
        >>> exists('thomas@goodcrypto.local')
        False
    '''

    name, address = parse_address(email)
    contact = get(address)
    found = contact is not None and contact.email == address
    log_message("{} <{}> contact exists: {}".format(name, address, found))

    return found

def get(email):
    ''' 
        Get the contact that matches the email address.

        Test an unknown email address so we're sure of the result.
        See the unittest to understand how to really use this function.
        
        >>> # In honor of Micah Lee, who helped Glenn Greenwald and others learn how to 
        >>> # secure their computers from being hacked.
        >>> get('micah@goodcrypto.local') is None
        True

        Test the extreme cases.
        >>> get('invalid@@address') is None
        True
        >>> get(None) is None
        True
    '''

    address = None
    contact = None

    try:
        if email is not None:
            _, address = parse_address(email)
            contact = Contact.objects.get(email=address)
    except Contact.DoesNotExist:
        contact = None
    except Exception:
        contact = None
        log_message(format_exc())

    log_message("got {}: {}".format(address, contact != None))

    return contact

def add(email, encryption_program, fingerprint=None):
    '''
        Add a contact and related settings.

        >>> # In honor of Thomas Drake, a whistleblower about Trailblazer, a NSA mass surveillance project.
        >>> email = 'thomas@goodcrypto.remote'
        >>> encryption_software = crypto_software.get(KeyFactory.DEFAULT_ENCRYPTION_NAME)
        >>> contact = add(email, KeyFactory.DEFAULT_ENCRYPTION_NAME)
        >>> contact.email
        'thomas@goodcrypto.remote'
        >>> contacts_crypto = ContactsCrypto.objects.get(
        ...    contact=contact, encryption_software=encryption_software)
        >>> contacts_crypto is not None
        True
        >>> contact.delete()
        >>> contact = add(None, encryption_software)
        >>> contact is None
        True
        >>> contact = add(email, None)
        >>> contact.email
        'thomas@goodcrypto.remote'
        >>> get_contacts_crypto(email)
        []
        >>> contact.delete()
        >>> contact = add(None, None)
        >>> contact is None
        True
    '''

    try:
        user_name, email_address = parse_address(email)
        if email_address is None:
            contact = None
        else:
            try:
                contact = Contact.objects.get(email=email_address)
                
                # update the user name if it's been given and it differs from the name in the DB
                if user_name is not None and contact.user_name != user_name:
                    contact.user_name = user_name
                    contact.save()
            except Contact.DoesNotExist:
                log_message('creating a contact for {}'.format(email_address))
                contact = Contact.objects.create(email=email_address, user_name=user_name)
            except Exception:
                log_message(format_exc())
                contact = None

        if encryption_program is None:
            log_message("no encryption software defined so not creating contact's crytpo record")
        else:
            # add a corresponding record for the contact's crypto program
            encryption_software = crypto_software.get(encryption_program)
            if contact is None or encryption_software is None:
                log_message('no contact and/or encryption software defined')
            else:
                try:
                    contacts_crypto = ContactsCrypto.objects.get(
                      contact=contact, encryption_software=encryption_software)
                    if fingerprint is not None and contacts_crypto.fingerprint != fingerprint:
                        contacts_crypto.fingerprint = fingerprint
                        contacts_crypto.save()
                except ContactsCrypto.DoesNotExist:
                    contacts_crypto = ContactsCrypto.objects.create(
                        contact=contact, encryption_software=encryption_software, fingerprint=fingerprint)
                    log_message("created {} crypto record for {} with {} fingerprint".format(
                        encryption_software, email, fingerprint))
                except:
                    log_message(format_exc())

    except Exception:
        contact = None
        log_message(format_exc())

    return contact

def delete(email_or_address):
    '''
        Delete the contact with a matching email address.

        >>> # In honor of Amy Goodman, who hosts Democracy Now!
        # returns true because the address doesn't exist, even though it wasn't necessary to delete it.
        >>> delete('amy@goodcrypto.local')
        True
        
        # test the extreme cases
        >>> delete(None)
        False
    '''

    result_ok = True
    try:
        if isinstance(email_or_address, str):
            name, address = parse_address(email_or_address)
            contact = get(address)
            if contact is None:
                log_message('no {} <{}> contact to delete'.format(name, address))
            else:
                contact = get(contact.email)
                if contact is None:
                    log_message('{}does not exist so need to delete'.format(email_or_address))
                else:
                    contact.delete()
                    log_message("deleted {}".format(contact.email))
        elif email_or_address is None:
            result_ok = False
        else:
            contact = email_or_address
            contact.delete()
            
    except Exception:
        result_ok = False
        log_message(format_exc())

    return result_ok

def get_contacts_crypto(email, encryption_name=None):
    ''' 
        Get the ContactsCrypto record that matches the encryption_name for this email.
        If the encryption_name is None, then get the query results of all the ContactsCrypto for this email.

        # Test extreme case. See unittests to see how to use this function.
        >>> get_contacts_crypto(None) == None
        True
    '''

    query_results = None
    try:
        _, address = parse_address(email)
        if email and len(address) > 0:
            if encryption_name is None:
                query_results = ContactsCrypto.objects.filter(contact__email=address)
            else:
                encryption_software = crypto_software.get(encryption_name)
                if encryption_software is None:
                    query_results = None
                else:
                    query_results = ContactsCrypto.objects.get(
                       contact__email=address, encryption_software=encryption_software)

            if query_results is None:
                log_message("{} does not have any encryption software defined".format(address))
            else:
                if isinstance(query_results, QuerySet):
                    log_message("{} has {} encryption software defined".format(email, len(query_results)))
                else:
                    log_message("{} already has 1 encryption software defined".format(email))
        else:
            log_message("{} does not have an email address".format(email))
    except ContactsCrypto.DoesNotExist:
        log_message('{} does not use {}'.format(email, encryption_software))
    except Contact.DoesNotExist:
        log_message('{} does not use the exist in the contacts table'.format(email))
    except Exception:
        log_message(format_exc())
        
    log_message("query results: {}".format(query_results))

    return query_results

def delete_contacts_crypto(email, encryption_name):
    ''' 
        Delete the ContactsCrypto record that matches the encryption_name for this email.

        >>> # In honor of Mark Smith, one of the developers for Tor Browser.
        >>> delete_contacts_crypto('mark@goodcrypto.local', 'GPG')
        False
    '''

    contacts_crypto = get_contacts_crypto(email, encryption_name=encryption_name)
    if contacts_crypto is None:
        result_ok = False
    else:
        try:
            contacts_crypto.delete()
            result_ok = True
        except Exception:
            result_ok = False
            log_message(format_exc())

    log_message("deleted {} crypto for {}: {}".format(encryption_name, email, result_ok))

    return result_ok

def get_fingerprint(email, encryption_name):
    ''' 
        Get the fingerprint for the encryption software for this email.

        >>> from goodcrypto.oce.constants import EDWARD_LOCAL_USER
        >>> fingerprint, verified = get_fingerprint(EDWARD_LOCAL_USER, KeyFactory.DEFAULT_ENCRYPTION_NAME)
        >>> len(fingerprint) > 0
        True
    '''

    if email is None or encryption_name is None:
        fingerprint = None
        verified = False
        log_message("missing data to get fingerprint; email: {} encryption: {}".format(email, encryption_name))
    else:
        log_message("getting {} fingerprint for {}".format(encryption_name, email))
        contacts_crypto = get_contacts_crypto(email, encryption_name=encryption_name)
        if contacts_crypto is None:
            fingerprint = None
            verified = False
            log_message("unable to get contact's {} record".format(encryption_name))
        else:
            if isinstance(contacts_crypto, QuerySet):
                fingerprint = contacts_crypto[0].fingerprint
                verified = contacts_crypto[0].verified
            else:
                fingerprint = contacts_crypto.fingerprint
                verified = contacts_crypto.verified
            log_message("{} {} unformatted fingerprint: {}".format(email, encryption_name, fingerprint))
            
    log_message("{} {} fingerprint: {}".format(email, encryption_name, fingerprint))

    return fingerprint, verified

def update_fingerprint(email, encryption_name, new_fingerprint, verified=False):
    ''' 
        Set the fingerprint for the encryption software for this email.
        If the fingerprint doesn't match the crypto's fingerprint, it won't
        be saved in the database.

        >>> # In honor of Linus Nordberg, Swedish advocate for Tor.
        >>> email = 'linus@goodcrypto.remote'
        >>> update_fingerprint(email, KeyFactory.DEFAULT_ENCRYPTION_NAME, '1234')
        True
        >>> delete(email)
        True
    '''

    if email is None or encryption_name is None:
        result_ok = False
        log_message("missing data to save {} fingerprint for {}".format(encryption_name, email))
    else:
        log_message('updating {} fingerprint for {}'.format(encryption_name, email))
        contacts_crypto = get_contacts_crypto(email, encryption_name=encryption_name)
        if contacts_crypto is None:
            contact = add(email, encryption_name)
            contacts_crypto = get_contacts_crypto(email, encryption_name=encryption_name)

        if contacts_crypto is None:
            result_ok = False
            log_message("unable to save contact's {} fingerprint".format(encryption_name))
        else:
            try:
                need_update = False
                if new_fingerprint != contacts_crypto.fingerprint:
                    contacts_crypto.fingerprint = new_fingerprint
                    need_update = True
                    log_message("contacts_crypto fingerprint: {}".format(contacts_crypto.fingerprint))
                if contacts_crypto.verified != verified:
                    contacts_crypto.verified = verified
                    need_update = True
                    log_message('Updated verification status: {}'.format(verified))
                if need_update:
                    contacts_crypto.save()
                    log_message('saved changes')

                result_ok = True
            except:
                log_message(format_exc())
                result_ok = False

    return result_ok

def is_key_ok(email, encryption_name):
    '''
        Throws a CryptoException if the email address does not have a crypto key, or
        the key has expired, or the key's fingerprint does not match the fingerprint in the database.

        >>> from goodcrypto.oce.constants import EDWARD_LOCAL_USER_ADDR
        >>> is_key_ok(EDWARD_LOCAL_USER_ADDR, KeyFactory.DEFAULT_ENCRYPTION_NAME)
        True
        
        # In honor of Georg Koppen, works on Tor Browser, Torbutton, and our build automation.
        >>> email = 'Georg <georg@goodcrypto.remote>'
        >>> is_key_ok(email, KeyFactory.DEFAULT_ENCRYPTION_NAME)
        Traceback (most recent call last):
            ...
        CryptoException: 'There is no GPG key for Georg <georg@goodcrypto.remote>.'
    '''

    # we use NO_FINGERPRINT_IN_DB a few times because we don't want to get too technical

    key_ok = False
    encryption_software = crypto_software.get(encryption_name)
    if encryption_software is None:
        # this should never happen, but better be prepared
        log_message('no database entry for {}'.format(email))
        raise CryptoException(international_strings.NO_FINGERPRINT_IN_DB.format(encryption_name, email))
    else:
        key_crypto = KeyFactory.get_crypto(encryption_name, encryption_software.classname)
        if key_crypto is None:
            # this should never happen, but better to be prepared
            log_message('no plugin for {} with classname: {}'.format(
                encryption_name, encryption_software.classname))
            raise CryptoException(international_strings.NO_FINGERPRINT_IN_DB.format(encryption_name, email))
        else:
            # see if the crypto key exists
            crypto_fingerprint, expiration = key_crypto.get_fingerprint(email)
            if crypto_fingerprint is None:
                message = international_strings.NO_KEY_EXISTS.format(encryption_name, email)
                log_message(message)
                raise CryptoException(message)

            # if the key has expired, then raise an error
            if expiration is not None and key_crypto.fingerprint_expired(expiration):
                message = international_strings.KEY_EXPIRED_ON.format(encryption_name, email, expiration)
                log_message(message)
                raise CryptoException(message)
                
            database_fingerprint, verified = get_fingerprint(email, encryption_name)
            # if there isn't a fingerprint, then try to save the crypto fingerprint
            if database_fingerprint is None or len(database_fingerprint.strip()) <= 0:
                contacts_encryption = get_contacts_crypto(email, encryption_name=encryption_name)
                if contacts_encryption is not None and contacts_encryption.fingerprint is None:
                    database_fingerprint = crypto_fingerprint
                    contacts_encryption.fingerprint = database_fingerprint
                    contacts_encryption.save()
                    log_message('updated {} fingerprint for {}'.format(encryption_name, email))

            if database_fingerprint is None or len(database_fingerprint.strip()) <= 0:
                error_message = international_strings.NO_FINGERPRINT_IN_DB.format(encryption_name, email)
                log_message(error_message)
                raise CryptoException(error_message)
            else:
                # finally verify the fingerprints agree
                if database_fingerprint.lower() == crypto_fingerprint.lower():
                    key_ok = True
                else:
                    message = international_strings.MISMATCHED_FINGERPRINTS.format(encryption_name, email)
                    log_message(message)
                    raise CryptoException(message)

            log_message('{} fingerprints agree and key has not expired for {}'.format(
              encryption_name, email))
            
    return key_ok

def get_public_key(email, encryption_software):
    ''' 
        Get the public key for the encryption software for this email.

        >>> from goodcrypto.oce.constants import EDWARD_LOCAL_USER
        >>> encryption_software = crypto_software.get(KeyFactory.DEFAULT_ENCRYPTION_NAME)
        >>> public_key = get_public_key(EDWARD_LOCAL_USER, encryption_software)
        >>> public_key is not None
        True
    '''

    if email is None or encryption_software is None:
        public_key = None
        encryption_name = ''
    else:
        encryption_name = encryption_software.name
        plugin = KeyFactory.get_crypto(encryption_name, encryption_software.classname)
        if plugin is None:
            public_key = None
            log_message('no plugin for {} with classname: {}'.format(
                encryption_software.name, encryption_software.classname))
        else:
            public_key = plugin.export_public(email)
        
    log_message("{} {} public_key\n{}".format(email, encryption_name, public_key))

    return public_key

def import_public_key(email, encryption_software, public_key):
    '''
        Import a public key and add an associated contact record.
        
        >>> # Test extreme cases
        >>> result_ok, status = import_public_key(None, None, None)
        >>> result_ok
        False
        
        >>> # In honor of First Sergeant Eden, who publicly denounced and refused to serve in operations 
        >>> # involving the occupied Palestinian territories because of the widespread surveillance of 
        >>> # innocent residents.
        >>> result_ok, status = import_public_key('eden@goodcrypto.remote', None, None)
        >>> result_ok
        False
    '''

    def import_key(email, encryption_name, public_key, user_id, plugin):
        ''' Import the key and return the fingerprint. '''

        status = fingerprint = None
        result_ok = False

        user_name, email_address = parse_address(email)
        _, key_address = parse_address(user_id)
        if email_address.lower() == key_address.lower():
            fingerprints = plugin.import_public(public_key)
            if len(fingerprints) > 0:
                fingerprint = fingerprints[0]

                status = international_strings.KEY_IMPORT_GOOD.format(fingerprint)
                result_ok = True
            else:
                result_ok = False
                status = 'Unable to import key'
        else:
            result_ok = False
            status = international_strings.WRONG_CONTACT_KEY.format(key_address, email_address)
            
        return result_ok, status, fingerprint

    if email is None or encryption_software is None or public_key is None:
        result_ok = False
        status = international_strings.IMPORT_MISSING_DATA
        log_message('email: {} / crypto: {} / public key: {}'.format(
           email, encryption_software, public_key))
    else:
        plugin = KeyFactory.get_crypto(encryption_software.name, encryption_software.classname)
        if plugin is None:
            result_ok = False
            status = international_strings.CRYPTO_NOT_SUPPORTED.format(encryption_software.name)
            log_message('no plugin for {} with classname: {}'.format(
                encryption_software.name, encryption_software.classname))
        else:
            user_ids = plugin.get_user_ids_from_key(public_key)
            log_message('user ids: {}'.format(user_ids))
            if user_ids is None:
                result_ok = False
                status = international_strings.PUBLIC_KEY_INVALID
            elif len(user_ids) > 0:
                result_ok, status, fingerprint = import_key(
                  email, encryption_software.name, public_key, user_ids[0], plugin)
                for user_id in user_ids:
                    contact = add(user_id, encryption_software.name, fingerprint=fingerprint)
                    log_message('added contact for: {}'.format(contact))

        log_message("Imported public {} key for {} ok: {}".format(encryption_software, email, result_ok))

    if not result_ok:
        log_message(status)

    return result_ok, status
    
def update_accepted_crypto(email, encryption_software_list):
    ''' Update the list of encryption software accepted by user.
    
        # Test extreme case. See unittests to see how to use this function.
        >>> update_accepted_crypto(None, None)
    '''

    if email is None:
        log_message("email not defined so no need to update accepted crypto")
    elif encryption_software_list is None or len(encryption_software_list) <= 0:
        log_message('no encryption programs defined for {}'.format(email))
    else:
        contact = get(email)
        if contact is None:
            # if the contact doesn't exist, then add them with the first encryption program
            encryption_program = encryption_software_list[0]
            contact = add(email, encryption_program)
            log_message("added {} to contacts".format(email))

        # associate each encryption program in the list with this contact
        for encryption_program in encryption_software_list:
            try:
                contacts_crypto = get_contacts_crypto(email, encryption_program)
                if contacts_crypto is None:
                    encryption_software = crypto_software.get(encryption_program)
                    if encryption_software is None:
                        log_message('{} encryption software unknown'.format(encryption_program))
                        log_message(
                          'unable to add contacts crypt for {} using {} encryption software unknown'.format(email, encryption_program))
                    else:
                        ContactsCrypto.objects.create(
                            contact=contact, encryption_software=encryption_software)
            except Exception:
                log_message(format_exc())
    
def get_encryption_names(email):
    '''
        Get a list of all the encryption program names for this email.
  
        # Test extreme case. See unittests to see how to use this function.
        >>> get_encryption_names(None)
        []
    '''

    encryption_names = []

    _, address = parse_address(email)
    if address and len(address) > 0:
        query_results = get_contacts_crypto(address)
        if query_results:
            log_message("{} has {} address(es)".format(address, len(query_results)))
            for contacts_encryption in query_results:
                encryption_name = contacts_encryption.encryption_software.name
                encryption_names.append(encryption_name)
                log_message("{} encryption software: {}".format(email, encryption_name))
        else:
            log_message("no encryption software for this contact")
    else:
        log_message("unable to get address from {}".format(email))

    return encryption_names

def get_contact_list(encryption_name=None):
    '''
        Get a list of all the contacts or 
        a list of all contacts that use the encryption software.

        # Test extreme case. See unittests to see how to use this function.
        >>> get_contact_list(encryption_name='Unknown encryption')
        []
    '''

    contact_list = []
    if encryption_name is None:
        try:
            contacts = Contact.objects.all()
            if contacts:
                for contact in contacts:
                    contact_list.append(contact.email)
                    log_message("email: {}".format(contact.email))
            else:
                log_message('no contacts')
        except Contact.DoesNotExist:
            log_message('no contact')
        except Exception:
            log_message(format_exc())

    else:
        try:
            query_results = ContactsCrypto.objects.filter(
                encryption_software__name=encryption_name, encryption_software__active=True)
            if query_results:
                for contacts_encryption in query_results:
                    contact_list.append(contacts_encryption.contact.email)
                    log_message("contact: {}".format(contacts_encryption))
            else:
                log_message('no contacts using {}'.format(encryption_name))
        except ContactsCrypto.DoesNotExist:
            log_message('no contacts with crypto')
        except Exception:
            log_message(format_exc())

    return contact_list

def log_message(message):
    '''
        Log a message to the local log.
        
        >>> import os.path
        >>> from syr.log import BASE_LOG_DIR
        >>> from syr.user import whoami
        >>> log_message('test')
        >>> os.path.exists(os.path.join(BASE_LOG_DIR, whoami(), 'goodcrypto.mail.contacts.log'))
        True
    '''

    global _log
    
    if _log is None:
        _log = LogFile()

    _log.write(message)
