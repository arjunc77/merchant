# -*- coding: utf-8 *-*
from billing import Integration, IntegrationNotConfigured
from django.conf import settings
from django_ogone.ogone import Ogone
from django.shortcuts import render_to_response
from django.template import RequestContext
from django.conf.urls import patterns, url
from django_ogone.status_codes import get_status_category, get_status_description
from django_ogone.signals import ogone_payment_accepted, ogone_payment_failed, ogone_payment_cancelled
from django.http import HttpResponse
from billing.utils.utilities import Bunch
from billing.forms.ogone_payments_forms import OgonePaymentsForm


class OgonePaymentsIntegration(Integration):
    display_name = "Ogone Payments Integration"
    template = "billing/ogone_payments.html"

    def __init__(self, options=None):
        if not options:
            options = {}
        super(OgonePaymentsIntegration, self).__init__(options=options)
        merchant_settings = getattr(settings, "MERCHANT_SETTINGS")
        if not merchant_settings or not merchant_settings.get("ogone_payments"):
            raise IntegrationNotConfigured("The '%s' integration is not correctly "
                                       "configured." % self.display_name)
        bunch = Bunch()
        bunch.update(merchant_settings["ogone_payments"])
        self.settings = bunch

    @property
    def service_url(self):
        return Ogone.get_action(production=not settings.MERCHANT_TEST_MODE)

    def ogone_notify_handler(self, request):
        response = Ogone(request=request, settings=self.settings)
        if response.is_valid():
            fpath = request.get_full_path()
            query_string = fpath.split("?", 1)[1]
            transaction_feedback = query_string.split('&')
            result = {}
            for item in transaction_feedback:
                k, v = item.split("=")
                result[k] = v

            # Default transaction feedback parameters
            status = result.get('STATUS', False)
            orderid = result.get('orderID', '')
            payid = result.get('PAYID', '')
            ncerror = result.get('NCERROR', '')

            amount = result.get('amount', '')
            currency = result.get('currency', '')

            if status and get_status_category(int(status)) == 'success':
                ogone_payment_accepted.send(sender=self, order_id=orderid, \
                    amount=amount, currency=currency, pay_id=payid, status=status, ncerror=ncerror)
                return self.ogone_success_handler(request, response=result, description=get_status_description(int(status)))

            if status and get_status_category(int(status)) == 'cancel':
                ogone_payment_cancelled.send(sender=self, order_id=orderid, \
                    amount=amount, currency=currency, pay_id=payid, status=status, ncerror=ncerror)
                return self.ogone_cancel_handler(request, response=result, description=get_status_description(int(status)))

            if status and get_status_category(int(status)) == 'decline' or 'exception':
                ogone_payment_failed.send(sender=self, order_id=orderid, \
                    amount=amount, currency=currency, pay_id=payid, status=status, ncerror=ncerror)
                return self.ogone_failure_handler(request, response=result, description=get_status_description(int(status)))
        else:
            return HttpResponse('signature validation failed!')

    def ogone_success_handler(self, request, response=None, description=''):
        return render_to_response("billing/ogone_success.html",
                                  {"response": response, "message": description},
                                  context_instance=RequestContext(request))

    def ogone_failure_handler(self, request, response=None, description=''):
        return render_to_response("billing/ogone_failure.html",
                                  {"response": response, "message": description},
                                  context_instance=RequestContext(request))

    def ogone_cancel_handler(self, request, response=None, description=''):
        return render_to_response("billing/ogone_cancel.html",
                                  {"response": response, "message": description},
                                  context_instance=RequestContext(request))

    def get_urls(self):
        urlpatterns = patterns('',
           url('^ogone_notify_handler/$', self.ogone_notify_handler, name="ogone_notify_handler"),)
        return urlpatterns

    def add_fields(self, params):
        for (key, val) in params.iteritems():
            if isinstance(val, dict):
                new_params = {}
                for k in val:
                    new_params["%s__%s" % (key, k)] = val[k]
                self.add_fields(new_params)
            else:
                self.add_field(key, val)

    def form_class(self):
        return OgonePaymentsForm

    def generate_form(self):
        # form = self.form_class()(initial=self.fields)
        # The above form has SHASIGN field which needs to be calculated.
        # It's easier to use the Ogone module's get_form method which takes care of that.
        form = Ogone.get_form(self.fields, settings=self.settings)
        return form
