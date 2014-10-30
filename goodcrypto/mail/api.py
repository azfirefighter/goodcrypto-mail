'''
    Copyright 2014 GoodCrypto
    Last modified: 2014-10-13

    This file is open source, licensed under GPLv3 <http://www.gnu.org/licenses/>.
'''

import json, os
from traceback import format_exc

from django.shortcuts import render_to_response
from django.template import RequestContext
from django.http import HttpResponsePermanentRedirect

from goodcrypto import api_constants
from goodcrypto.mail import contacts
from goodcrypto.mail.forms import APIForm
from goodcrypto.mail.options import set_domain, set_mail_server_address
from goodcrypto.mail.utils import get_mail_status, create_superuser
from goodcrypto.utils.log_file import LogFile
from syr.utils import get_remote_ip, strip_input



class MailAPI(object):
    '''Handle the API for GoodCrypto Mail.'''
    
    def __init__(self):
        self.log = LogFile('goodcrypto.mail.api.log')
        
    def interface(self, request):
        '''Interface with the server through the API.
        
           All requests must be via a POST.
        '''
    
        # final results and error_messages of the actions
        result = None
        
        ok = False
        response = None
    
        try:
            self.action = self.sysadmin = self.domain = self.mail_server_address = None
            self.public_key = self.encryption_name = self.fingerprint = None
            self.user_name = self.password = None
            self.ip = get_remote_ip(request)
            self.log.write('attempting mail api call from {}'.format(self.ip))

            if request.method == 'POST':
                try:
                    form = APIForm(request.POST)
                    if form.is_valid():
                        cleaned_data = form.cleaned_data

                        self.action = cleaned_data.get(api_constants.ACTION_KEY)
                        self.log.write('action: {}'.format(self.action))
                        if self.action == api_constants.CREATE_USER:
                            self.sysadmin = strip_input(cleaned_data.get(api_constants.SYSADMIN_KEY))
                            self.log.write('sysadmin: {}'.format(self.sysadmin))
                        elif self.action == api_constants.CONFIGURE:
                            self.domain = strip_input(cleaned_data.get(api_constants.DOMAIN_KEY))
                            self.log.write('domain: {}'.format(self.domain))
                            self.mail_server_address = strip_input(cleaned_data.get(api_constants.MTA_ADDRESS_KEY))
                            self.log.write('mail_server_address: {}'.format(self.mail_server_address))
                        elif self.action == api_constants.IMPORT_KEY:
                            self.public_key = strip_input(cleaned_data.get(api_constants.PUBLIC_KEY))
                            self.encryption_name = strip_input(cleaned_data.get(api_constants.ENCRYPTION_NAME_KEY))
                            self.log.write('encryption_name: {}'.format(self.encryption_name))
                            self.fingerprint = strip_input(cleaned_data.get(api_constants.FINGERPRINT_KEY))
                            self.log.write('fingerprint: {}'.format(self.fingerprint))
                            self.user_name = strip_input(cleaned_data.get(api_constants.USER_NAME_KEY))
                            self.log.write('user_name: {}'.format(self.user_name))
                            self.sysadmin = strip_input(cleaned_data.get(api_constants.SYSADMIN_KEY))
                            self.log.write('sysadmin: {}'.format(self.sysadmin))
                            self.password = strip_input(cleaned_data.get(api_constants.PASSWORD_KEY))

                        result = self.take_api_action()
    
                    else:
                        result = self.format_bad_result('Invalid form')
                        self.log_attempted_access(result)
                
                        self.log.write('api form is not valid')
                        self.log_bad_form(request, form)
                    
                except:
                    result = self.format_bad_result('Unknown error')
                    self.log_attempted_access(result)

                    self.log.write(format_exc())
                    self.log.write('unexpected error while parsing input')
            else:
                self.log_attempted_access('Attempted GET connection')
                
                self.log.write('redirecting api GET request to website')
                response = HttpResponsePermanentRedirect(api_constants.SYSTEM_API_URL)
                        
            if response is None:
                response = self.get_api_response(request, result)
                
        except:
            self.log.write(format_exc())
            response = HttpResponsePermanentRedirect(api_constants.SYSTEM_API_URL)
    
        return response
    
    
    def take_api_action(self):
    
        result = None
        
        ok, error_message = self.is_data_ok()
        if ok:
            if self.action == api_constants.CONFIGURE:
                set_domain(self.domain)
                set_mail_server_address(self.mail_server_address)
                result = self.format_result(api_constants.CONFIGURE, ok)
                self.log.write('configure result: {}'.format(result))

            elif self.action == api_constants.CREATE_USER:
                password, error_message = create_superuser(self.sysadmin)
                if password is None:
                    result = self.format_bad_result(error_message)
                else:
                    result = self.format_message_result(api_constants.CREATE_USER, ok, password)
                self.log.write('create user result: {}'.format(result))

            elif self.action == api_constants.STATUS:
                result = self.format_result(api_constants.STATUS, get_mail_status())
                self.log.write('status result: {}'.format(result))
                
            elif self.action == api_constants.IMPORT_KEY:
                from goodcrypto.mail.views import import_public_key
                
                result_ok, status, fingerprint_ok = import_public_key(
                    self.encryption_name, self.public_key, self.user_name, self.fingerprint)
                if result_ok:
                    result = self.format_result(api_constants.IMPORT_KEY, True)
                else:
                    result = self.format_bad_result(status)
                self.log.write('create user result: {}'.format(result))

            else:
                ok = False
                error_message = 'Bad action: {}'.format(self.action)
                result = self.format_bad_result(error_message)
                self.log.write('bad action result: {}'.format(result))
    
        else:
            result = self.format_bad_result(error_message)
            self.log.write('data is bad')

        return result
    
    def is_data_ok(self):
        '''Check if all the required data is present.'''
        
        error_message = ''
        ok = False
        
        if self.has_content(self.action):
            if self.action == api_constants.CONFIGURE:
                if self.has_content(self.domain) and self.has_content(self.mail_server_address):
                    ok = True
                    self.log.write('minimum configure data found')

            elif self.action == api_constants.CREATE_USER:
                if self.has_content(self.sysadmin):
                    ok = True
                    self.log.write('minimum create user data found: {}'.format(self.sysadmin))

            elif self.action == api_constants.STATUS:
                ok = True
                self.log.write('status request found')

            elif self.action == api_constants.IMPORT_KEY:
                if (self.has_content(self.public_key) and 
                    self.has_content(self.encryption_name) and 
                    self.has_content(self.sysadmin) and
                    self.has_content(self.password)):
                    ok = True
                    self.log.write('minimum import key data found')

            if not ok:
                error_message = 'Missing required data'
                self.log.write('missing required data')

        else:
            ok = False
            error_message = 'Missing required action'
            self.log.write('missing required action')
            
        return ok, error_message

    def has_content(self, value):
        '''Check that the value has content.'''
        
        try:
            str_value = str(value)
            if str_value is None or len(str_value.strip()) <= 0:
                ok = False
            else:
                ok = True
        except:
            ok = False
            self.log.write(format_exc())
            
        return ok
            
    def format_result(self, action, ok, error_message=None):
        '''Format the action's result.'''
    
        if error_message is None:
            result = {api_constants.ACTION_KEY: action, api_constants.OK_KEY: ok}
        else:
            result = {
              api_constants.ACTION_KEY: action, 
              api_constants.OK_KEY: ok, 
              api_constants.ERROR_KEY: error_message
            }
            
        return result
        
    def format_message_result(self, action, ok, message):
        '''Format the action's result.'''
    
        result = {
          api_constants.ACTION_KEY: action, 
          api_constants.OK_KEY: ok, 
          api_constants.MESSAGE_LABEL: message
        }
            
        return result

    def format_bad_result(self, error_message):
        '''Format the bad result for the action.'''
        
        result = None
        
        if self.action and len(self.action) > 0:
            result = self.format_result(self.action, False, error_message=error_message)
        else:
            result = self.format_result('Unknown', False, error_message=error_message)
            
        self.log.write('action result: {}'.format(error_message))
    
        return result
        
    
    def get_api_response(self, request, result):
        ''' Get API reponse as JSON. '''

        json_result = json.dumps(result)
        self.log.write('json results: {}'.format(''.join(json_result)))
    
        response = render_to_response('mail/api_response.html',
            {'result': ''.join(json_result),}, 
            context_instance=RequestContext(request))
        
        return response
    
    
    def log_attempted_access(self, results):
        '''Log an attempted access to the api.'''
     
        self.log.write('attempted access from {} for {}'.format(self.ip, results))
        
    def log_bad_form(self, request, form):
        ''' Log the bad fields entered.'''
        
        # see django.contrib.formtools.utils.security_hash()
        # for example of form traversal
        for field in form:
            if (hasattr(form, 'cleaned_data') and 
                field.name in form.cleaned_data):
                name = field.name
            else:
                # mark invalid data
                name = '__invalid__' + field.name
            self.log.write('name: {}; data: {}'.format(name, field.data))
        try:
            if form.name.errors:
                self.log.write('  ' + form.name.errors)
            if form.email.errors:
                self.log.write('  ' + form.email.errors)
        except:
            pass
    
        self.log.write('logged bad api form')

