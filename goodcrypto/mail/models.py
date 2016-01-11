'''
    Models for Mail app.
    
    Better to use the goodcrypto.mail classes (e.g., Contacts, ContactsPasscodes) 
    to access data than access it directly via the Models. Using those classes will increase 
    the probability of future compatibility in case GoodCrypto uses another way to store data
    or moves to another framework which doesn't interface with databases the same way as django.

    Copyright 2014-2015 GoodCrypto
    Last modified: 2015-02-28

    This file is open source, licensed under GPLv3 <http://www.gnu.org/licenses/>.
'''
from django.core import validators
from django.db import models
from django.db.models.signals import post_delete, post_save

from goodcrypto.mail import constants
from goodcrypto.mail.model_signals import post_save_contacts_crypto, post_delete_contacts_crypto, post_save_options
from goodcrypto.mail.options import get_domain
from goodcrypto.mail.utils import email_in_domain
from goodcrypto.utils import i18n
# do not use LogFile because it references models.System
from syr.log import get_log

_log = get_log()

class EncryptionSoftware(models.Model):
    '''
        The encryption software available to goodcrypto.

        Create some encryption software
        >>> test_gpg = EncryptionSoftware.objects.create(
        ... name='TestAnotherGPG', active=True, classname='goodcrypto.oce.gpg_plugin.GPGPlugin')
        >>> str(test_gpg)
        'TestAnotherGPG'
        >>> test_gpg.__unicode__()
        'TestAnotherGPG'
        >>> test_gpg.delete()
    '''
    
    name = models.CharField(i18n('Name'),
       max_length=100, unique=True, blank=False,
       help_text=i18n('Name of the encryption software (e.g., GPG).'))

    active = models.BooleanField(i18n('Active?'), default=True,
       help_text=i18n('Is encryption software installed and available?'))
    
    classname = models.CharField(i18n('Classname'),
       max_length=100, blank=True, null=True,
       help_text=i18n("Leave blank unless you are using encryption software not supplied by GoodCrypto. See GoodCrypto's OCE docs for more details."))

    def __unicode__(self):
        return '{}'.format(self.name)

    class Meta:
        verbose_name = i18n('encryption software')
        verbose_name_plural = verbose_name
        
    
class LongEmailField(models.CharField):
    ''' A RFC3696/5321 compatible email address. 
    
        Django's default EmailField limits the max length to 75 characters.
    '''
    default_validators = [validators.validate_email]
    description = i18n("Email address")

    def __init__(self, *args, **kwargs):
        kwargs['max_length'] = kwargs.get('max_length', 254)
        models.CharField.__init__(self, *args, **kwargs)

    def formfield(self, **kwargs):
        from django import forms
        
        # As with CharField, this will cause email validation to be performed twice.
        defaults = {
            'form_class': forms.EmailField,
        }
        defaults.update(kwargs)
        return super(LongEmailField, self).formfield(**defaults)


class Contact(models.Model):
    ''' 
        Email addresses that use encryption.
    
        Contains both users whose email goodcrypto encrypt/decrypts and their correspondents.
        
        >>> # In honor of Arlo Breault, a developer for the Tor project.
        >>> # Create a contact with a full user name and email address
        >>> email = 'arlo@goodcrypto.remote'
        >>> contact = Contact.objects.create(email=email, user_name='Arlo')
        >>> contact.email
        'arlo@goodcrypto.remote'
        >>> contact.user_name
        'Arlo'
        >>> str(contact)
        'Arlo <arlo@goodcrypto.remote>'
        >>> contact.__unicode__()
        'Arlo <arlo@goodcrypto.remote>'
        >>> contact.delete()
        
        >>> # In honor of Andrea Shepard, a core Tor developer.
        >>> # Create a contact with only an email address
        >>> contact = Contact.objects.create(email='andrea@GoodCrypto.remote')
        >>> str(contact)
        'andrea@goodcrypto.remote'
        >>> contact.delete()
        
        >>> # In honor of Paul Syverson, one of the original designers of Tor.
        >>> # Create a contact with a mixed case email address
        >>> contact = Contact.objects.create(email='Paul@GoodCrypto.Remote')
        >>> contact.__unicode__()
        'paul@goodcrypto.remote'
        >>> contact.delete()
        
    '''
    
    email = LongEmailField(i18n('Email'), blank=False,
       unique=True, help_text=i18n('Email address of someone that uses encryption software.'))

    user_name = models.CharField(i18n('User name'),
       max_length=100, blank=True, null=True,
       help_text=i18n('Printable name for the contact. It is not required, but strongly recommended as encryption software often requires it.'))

    def save(self, *args, **kwargs):
        # maintain all addresses in lower case
        if self.email:
            self.email = self.email.lower()
        super(Contact, self).save(*args, **kwargs)
        # OperationalError: database is locked

    def __unicode__(self):
        if self.user_name and len(self.user_name.strip()) > 0:
            return '{} <{}>'.format(self.user_name, self.email)
        else:
            return '{}'.format(self.email)

    class Meta:
        verbose_name = i18n('contact')
        verbose_name_plural = i18n('contacts')


class ContactsCrypto(models.Model):
    ''' 
        The encryption software used by contacts.
    
        There can be multiple records for each contact because
        ideally, each contact can handle encrypting messages with
        multiple encryption programs.
        
        Contacts include the local users as well as those people they correspond.
        
        >>> # In honor of William Binney, a whistleblower about Trailblazer, a NSA mass surveillance project.
        >>> from django.db import IntegrityError
        >>> contact = Contact.objects.create(email='william@goodcrypto.remote')
        >>> gpg = EncryptionSoftware.objects.create(
        ... name='TestWilliamGPG', active=True, classname='goodcrypto.oce.gpg_plugin.GPGPlugin')
        >>> contacts_crypto = ContactsCrypto.objects.create(contact=contact, encryption_software=gpg)
        >>> str(contacts_crypto)
        'william@goodcrypto.remote: TestWilliamGPG'
        >>> contacts_crypto.__unicode__()
        'william@goodcrypto.remote: TestWilliamGPG'
        >>> contact.user_name = 'William'
        >>> contact.save()
        >>> contacts_crypto.__unicode__()
        'William <william@goodcrypto.remote>: TestWilliamGPG'
        >>> try:
        ...     ContactsCrypto.objects.create(contact=contact, encryption_software=gpg)
        ... except IntegrityError as error:
        ...     str(error).strip().startswith('duplicate key value violates unique constraint "mail_contactscrypto_contact_id_encryption_software_id_key"')
        True
        >>> contacts_crypto.delete()
        >>> contact.delete()
        >>> gpg.delete()
    '''
    
    contact = models.ForeignKey(Contact,
       help_text=i18n('Email address.'))
    
    encryption_software = models.ForeignKey(EncryptionSoftware,
       help_text=i18n('Encryption software used by this contact.'))

    fingerprint = models.CharField(i18n('Fingerprint'),
       max_length=100, blank=True, null=True,
       help_text=i18n("The fingerprint for the contact's public key."))

    verified = models.BooleanField(i18n('Verified?'), default=False,
       help_text=i18n('We strongly recommend that you verify this fingerprint in a secure manner, not via email.'))
    
    active = models.BooleanField(i18n('Active?'), default=True,
       help_text=i18n('If True, then the associate key will be used whenever possible. Otherwise, GoodCrypto will ignore the key.'))
    
    def __unicode__(self):
        return '{}: {}'.format(self.contact, self.encryption_software)

    class Meta:
        verbose_name = i18n("contact's encryption software")
        verbose_name_plural = verbose_name

        unique_together = ('contact', 'encryption_software')
post_save.connect(post_save_contacts_crypto, sender=ContactsCrypto)
post_delete.connect(post_delete_contacts_crypto, sender=ContactsCrypto)

class ContactsPasscode(models.Model):
    '''
        Private passcodes, also known as passphrases, for contacts.
        
        We'd prefer to keep salted hashes, but the underlying crypto software wants the
        passphrase in plain text. It's important that the goodcrypto server is kept behind
        a strong firewall.
        
        This table contains all the passcodes for contacts whose email goodcrypto manages. 
        Most contacts will not have a record in this table because GoodCrypto only manages
        email for local users.
        
        There is one record in this table for each contact's encryption software
        *if* goodcrypto encrypts and decrypts messages for that contact.
        
        >>> # In honor of Professional Academic Officer H, who co-signed letter and refused to serve in operations
        >>> # involving the occupied Palestinian territories because of the widespread surveillance of innocent residents.
        >>> from django.core.exceptions import ValidationError
        >>> from goodcrypto.mail.model_signals import TESTS_RUNNING
        >>> TESTS_RUNNING = True
        >>> gpg = EncryptionSoftware.objects.create(
        ...   name='TestHGPG', active=True, classname='goodcrypto.oce.gpg_plugin.GPGPlugin')
        >>> contact = Contact.objects.create(email='officer_h@goodcrypto.local')
        >>> contacts_crypto = ContactsCrypto.objects.create(contact=contact, encryption_software=gpg)
        >>> contacts_passcode = ContactsPasscode.objects.create(contacts_encryption=contacts_crypto, 
        ...  passcode='secret', auto_generated=False)
        >>> contacts_passcode is not None
        True
        >>> contact.delete()
        >>> gpg.delete()
        >>> TESTS_RUNNING = False
    '''
    
    EXPIRE_IN_DAYS = 'd'
    EXPIRE_IN_WEEKS = 'w'
    EXPIRE_IN_MONTHS = 'm'
    EXPIRE_IN_YEARS = 'y'
    EXPIRATION_CHOICES = (
      (EXPIRE_IN_DAYS, i18n('Days')),
      (EXPIRE_IN_WEEKS, i18n('Weeks')),
      (EXPIRE_IN_MONTHS, i18n('Months')),
      (EXPIRE_IN_YEARS, i18n('Years')),
    )

    # default time until key expires: 1 year
    DEFAULT_EXPIRATION_TIME = 1
    DEFAULT_EXPIRATION_PERIOD = EXPIRE_IN_YEARS

    contacts_encryption = models.OneToOneField(ContactsCrypto,
       help_text=i18n('Encryption software used by a contact.'))

    passcode = models.CharField(i18n('Passcode'),
       max_length=constants.PASSCODE_MAX_LENGTH, blank=True, null=True,
       help_text=i18n(
         'Secret passcode, also known as a passphrase, used with this encryption software. It is recommended that you allow GoodCrypto to create the passcode because it should be long and difficult to remember.'))

    auto_generated = models.BooleanField(i18n('Auto generate?'), default=True,
       help_text=i18n('Add a check mark if you want GoodCrypto to generate a private passcode.'))
    
    expires_in = models.PositiveSmallIntegerField(i18n('Expires in'), default=DEFAULT_EXPIRATION_TIME,
       help_text=i18n('The quantity of time the key is valid. If set to 0, it never expires which is not recommended.'))
    
    expiration_unit = models.CharField(max_length=1, default=DEFAULT_EXPIRATION_PERIOD, choices=EXPIRATION_CHOICES,
       help_text=i18n('The unit of time the key is valid.'))
    
    last_notified = models.DateTimeField(i18n('Last notified'), blank=True, null=True,
       help_text=i18n('Last date a notice about this key was sent to the user.'))
    
    def __unicode__(self):
        return '{}'.format(self.contacts_encryption)

    class Meta:
        verbose_name = i18n('passcode')
        verbose_name_plural = i18n('passcodes')

class MessageHistory(models.Model):
    '''
        Log of messages that were encrypted or decrypted.

        Each user can verify a message was encrypted before it was sent or it
        was decrypted by the GoodCrypto server. Users can only see details about
        messages they sent or received. This eliminates concerns about a message's
        tag being spoofed by a third party.
    '''
    
    DECRYPTED_MESSAGE_STATUS = 'd'
    ENCRYPTED_MESSAGE_STATUS = 'e'
    MESSAGE_STATUS = (
      (DECRYPTED_MESSAGE_STATUS, i18n('decrypted')),
      (ENCRYPTED_MESSAGE_STATUS, i18n('encrypted')),
    )
    MAX_ENCRYPTION_PROGRAMS = 50
    MAX_MESSAGE_DATE = 50
    MAX_MESSAGE_ID = 100
    MAX_VALIDATION_CODE = 25
    
    sender = LongEmailField(i18n('Sender email'), blank=False, unique=False,
              help_text=i18n('From user email address.'))
    
    recipient = LongEmailField(i18n('Recipient email'), blank=False,  unique=False,
                  help_text=i18n('To user email address.'))

    status = models.CharField(max_length=1, choices=MESSAGE_STATUS,
       help_text=i18n('Shows whether the message was decrypted or encrypted by your GoodCrypto server.'))
    
    encryption_programs = models.CharField(max_length=MAX_ENCRYPTION_PROGRAMS,
       help_text=i18n('List of encryption software programs used with this message.'))

    message_date = models.CharField(max_length=MAX_MESSAGE_DATE,
       help_text=i18n("The date from the message header or if there isn't one, then the date when message processed."))
    
    message_id = models.CharField(i18n('Message ID'), max_length=MAX_MESSAGE_ID, 
       help_text=i18n("The ID for the message from the header."))
    
    validation_code = models.CharField(i18n('Validation code'), max_length=MAX_VALIDATION_CODE, 
       help_text=i18n("The special code generated when the message is encrypted/decrypted."))
    
    def __unicode__(self):
        return '{}: {} at {}'.format(self.sender, self.recipient, self.message_date)

    class Meta:
        verbose_name = i18n('message history')
        verbose_name_plural = i18n('message history')

class Options(models.Model):
    ''' 
        GoodCrypto Mail settings. 
    
        >>> options = Options.objects.all()
        >>> options is not None
        True
        >>> len(options) == 1
        True
    '''

    DEFAULT_GOODCRYPTO_LISTEN_PORT = 10025
    DEFAULT_MTA_LISTEN_PORT = 10026
    
    mail_server_address = models.CharField(i18n('Mail server address'),
       max_length=100, blank=True, null=True,
       help_text=i18n("The address for the domain's mail transport agent (e.g., postfix, sendmail)."))
    
    goodcrypto_listen_port = models.PositiveSmallIntegerField(i18n('MTA inbound port'),
       default=DEFAULT_GOODCRYPTO_LISTEN_PORT,
       help_text=i18n("The port where the goodcrypto mail server listens for messages FROM the MTA."))
    
    mta_listen_port = models.PositiveSmallIntegerField(i18n('MTA outbound port'),
       default=DEFAULT_MTA_LISTEN_PORT,
       help_text=i18n("The port where the MTA listens for messages FROM the the goodcrypto mail server."))
    
    auto_exchange = models.BooleanField(i18n('Exchange public keys P2P'), default=True,
       help_text=i18n("Automatically exchange public keys P2P. Always include the sender's public key in the header."))
    
    create_private_keys = models.BooleanField(i18n('Create keys'), default=True,
       help_text=i18n("Generate keys for users who don't have one."))
    
    clear_sign = models.BooleanField(i18n('Clear sign mail'), default=False,
       help_text=i18n("If you elect to clear sign, then all outbound encrypted mail will include the sender's encrypted signature."))
    
    filter_html = models.BooleanField(i18n('Filter HTML'), default=True,
       help_text=i18n("GoodCrypto can remove HTML that may harm your system."))

    max_message_length = models.PositiveIntegerField(i18n('Max kilobytes of a message'), default=500120,
       help_text=i18n('The maximum size, in K, of encrypted/decrypted messages, including attachments. This helps prevent your mail system from being DOSed.'))

    domain = models.CharField(max_length=100, blank=True, null=True)

    subscription = models.CharField(max_length=100, blank=True, null=True)
    
    debugging_enabled = models.BooleanField(i18n('Enable diagnostic logs'), default=True,
       help_text=i18n('Activate logs to help debug unexpected behavior.'))
    
    require_key_verified = models.BooleanField(i18n('Require verify new keys'), default=False,
       help_text=i18n("Do not use a new public key until it is flagged as verified in the database."))
    
    login_to_view_fingerprints = models.BooleanField(i18n('Require login to view fingerprints'), default=False,
       help_text=i18n("Require that a user login to view any fingerprints."))
    
    login_to_export_keys = models.BooleanField(i18n('Require login to export keys'), default=False,
       help_text=i18n("Require that a user login to export any public keys."))
    
    add_keys_to_keyservers = models.BooleanField(i18n('Add keys to public keyservers'), default=False,
       help_text=i18n("Add public keys created by GoodCrypto to public keyservers?"))
    
    verify_new_keys_with_keyservers = models.BooleanField(i18n('Verify new keys with public keyservers'), default=False,
       help_text=i18n("Verify new public keys imported with public keyservers?"))
    
    goodcrypto_server_url = models.CharField(i18n('GoodCrypto server url'), 
        max_length=100, blank=True, null=True,
        help_text=i18n("The full url to reach your GoodCrypto server's website, including the port. For example, http://194.10.334.1:8080 or https://194.10.334.1:8443"))
    
    def __unicode__(self):
        return '{}'.format(self.mail_server_address)

    class Meta:
        verbose_name = i18n('options')
        verbose_name_plural = verbose_name
post_save.connect(post_save_options, sender=Options)

