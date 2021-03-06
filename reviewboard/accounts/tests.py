from __future__ import unicode_literals

import re

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test.client import RequestFactory
from djblets.registries.errors import ItemLookupError, RegistrationError
from djblets.testing.decorators import add_fixtures
from kgb import SpyAgency

from reviewboard.accounts.backends import (AuthBackend,
                                           get_enabled_auth_backends,
                                           INVALID_USERNAME_CHAR_REGEX,
                                           StandardAuthBackend)
from reviewboard.accounts.forms.pages import (AccountPageForm,
                                              ChangePasswordForm,
                                              ProfileForm)
from reviewboard.accounts.models import (LocalSiteProfile,
                                         Profile,
                                         ReviewRequestVisit,
                                         Trophy)
from reviewboard.accounts.pages import (AccountPage, get_page_classes,
                                        register_account_page_class,
                                        unregister_account_page_class)
from reviewboard.testing import TestCase


class AuthBackendTests(TestCase):
    """Testing authentication backends."""

    def _get_standard_auth_backend(self):
        backend = None

        for backend in get_enabled_auth_backends():
            # We do not use isinstance here because we specifically want a
            # StandardAuthBackend and not an instance of a subclass of it.
            if type(backend) is StandardAuthBackend:
                break

        self.assertIs(type(backend), StandardAuthBackend)

        return backend

    @add_fixtures(['test_users'])
    def test_get_or_create_user_exists(self):
        """Testing StandardAuthBackend.get_or_create_user when the requested
        user already exists
        """
        original_count = User.objects.count()

        user = User.objects.get(username='doc')
        backend = self._get_standard_auth_backend()
        result = backend.get_or_create_user('doc', None)

        self.assertEqual(original_count, User.objects.count())
        self.assertEqual(user, result)

    def test_get_or_create_user_new(self):
        """Testing StandardAuthBackend.get_or_create_user when the requested
        user does not exist
        """
        backend = self._get_standard_auth_backend()
        self.assertIsInstance(backend, StandardAuthBackend)
        user = backend.get_or_create_user('doc', None)

        self.assertIsNone(user)

    @add_fixtures(['test_users'])
    def test_get_user_exists(self):
        """Testing StandardAuthBackend.get_user when the requested user already
        exists
        """
        user = User.objects.get(username='doc')
        backend = self._get_standard_auth_backend()
        result = backend.get_user(user.pk)

        self.assertEqual(user, result)

    def test_get_user_not_exists(self):
        """Testing StandardAuthBackend.get_user when the requested user does
        not exist
        """
        backend = self._get_standard_auth_backend()
        result = backend.get_user(1)

        self.assertIsNone(result)


class ReviewRequestVisitTests(TestCase):
    """Testing the ReviewRequestVisit model"""

    fixtures = ['test_users']

    def test_default_visibility(self):
        """Testing default value of ReviewRequestVisit.visibility"""
        review_request = self.create_review_request(publish=True)
        self.client.login(username='admin', password='admin')
        self.client.get(review_request.get_absolute_url())

        visit = ReviewRequestVisit.objects.get(
            user__username='admin', review_request=review_request.id)

        self.assertEqual(visit.visibility, ReviewRequestVisit.VISIBLE)


class ProfileTests(TestCase):
    """Test the Profile model."""

    fixtures = ['test_users']

    def test_is_profile_visible_with_public(self):
        """Testing User.is_profile_public with public profiles."""
        user1 = User.objects.get(username='admin')
        user2 = User.objects.get(username='doc')

        self.assertTrue(user1.is_profile_visible(user2))

    def test_is_profile_visible_with_private(self):
        """Testing User.is_profile_public with private profiles."""
        user1 = User.objects.get(username='admin')
        user2 = User.objects.get(username='doc')

        profile = user1.get_profile()
        profile.is_private = True
        profile.save()

        self.assertFalse(user1.is_profile_visible(user2))
        self.assertTrue(user1.is_profile_visible(user1))

        user2.is_staff = True
        self.assertTrue(user1.is_profile_visible(user2))

    @add_fixtures(['test_scmtools', 'test_site'])
    def test_is_star_unstar_updating_count_correctly(self):
        """Testing if star, unstar affect review request counts correctly."""
        user1 = User.objects.get(username='admin')
        profile1 = user1.get_profile()
        review_request = self.create_review_request(publish=True)

        site_profile = profile1.site_profiles.get(local_site=None)

        profile1.star_review_request(review_request)
        site_profile = LocalSiteProfile.objects.get(pk=site_profile.pk)

        self.assertTrue(review_request in
                        profile1.starred_review_requests.all())
        self.assertEqual(site_profile.starred_public_request_count, 1)

        profile1.unstar_review_request(review_request)
        site_profile = LocalSiteProfile.objects.get(pk=site_profile.pk)

        self.assertFalse(review_request in
                         profile1.starred_review_requests.all())
        self.assertEqual(site_profile.starred_public_request_count, 0)


class AccountPageTests(TestCase):
    """Test account page functionality."""

    builtin_pages = set(['settings', 'authentication', 'profile', 'groups',
                         'api-tokens'])

    def tearDown(self):
        """Uninitialize this test case."""
        super(AccountPageTests, self).tearDown()
        AccountPage.registry.reset()

    def test_default_pages(self):
        """Testing default list of account pages."""
        page_classes = list(get_page_classes())
        self.assertEqual(len(page_classes), len(self.builtin_pages))

        page_class_ids = [page_cls.page_id for page_cls in page_classes]
        self.assertEqual(set(page_class_ids), self.builtin_pages)

    def test_register_account_page_class(self):
        """Testing register_account_page_class."""
        class MyPage(AccountPage):
            page_id = 'test-page'
            page_title = 'Test Page'

        register_account_page_class(MyPage)

        page_classes = list(get_page_classes())
        self.assertEqual(len(page_classes), len(self.builtin_pages) + 1)
        self.assertEqual(page_classes[-1], MyPage)

    def test_register_account_page_class_with_duplicate(self):
        """Testing register_account_page_class with duplicate page."""
        class MyPage(AccountPage):
            page_id = 'test-page'
            page_title = 'Test Page'

        register_account_page_class(MyPage)

        with self.assertRaises(RegistrationError):
            register_account_page_class(MyPage)

    def test_unregister_account_page_class(self):
        """Testing unregister_account_page_class."""
        class MyPage(AccountPage):
            page_id = 'test-page'
            page_title = 'Test Page'

        register_account_page_class(MyPage)
        unregister_account_page_class(MyPage)

        page_classes = list(get_page_classes())
        self.assertEqual(len(page_classes), len(self.builtin_pages))

    def test_unregister_unknown_account_page_class(self):
        """Testing unregister_account_page_class with unknown page."""
        class MyPage(AccountPage):
            page_id = 'test-page'
            page_title = 'Test Page'

        with self.assertRaises(ItemLookupError):
            unregister_account_page_class(MyPage)

    def test_add_form_to_page(self):
        """Testing AccountPage.add_form."""
        class MyPage(AccountPage):
            page_id = 'test-page'
            page_title = 'Test Page'

        class MyForm(AccountPageForm):
            form_id = 'test-form'

        register_account_page_class(MyPage)
        MyPage.add_form(MyForm)

        self.assertEqual(MyPage.form_classes, [MyForm])

    def test_add_duplicate_form_to_page(self):
        """Testing AccountPage.add_form with duplicate form ID."""
        class MyForm(AccountPageForm):
            form_id = 'test-form'

        class MyPage(AccountPage):
            page_id = 'test-page'
            page_title = 'Test Page'
            form_classes = [MyForm]

        register_account_page_class(MyPage)

        with self.assertRaises(RegistrationError):
            MyPage.add_form(MyForm)

        self.assertEqual(MyPage.form_classes, [MyForm])

    def test_remove_form_from_page(self):
        """Testing AccountPage.remove_form."""
        class MyForm(AccountPageForm):
            form_id = 'test-form'

        class MyPage(AccountPage):
            page_id = 'test-page'
            page_title = 'Test Page'
            form_classes = [MyForm]

        register_account_page_class(MyPage)
        MyPage.remove_form(MyForm)

        self.assertEqual(MyPage.form_classes, [])

    def test_remove_unknown_form_from_page(self):
        """Testing AccountPage.remove_form with unknown form."""
        class MyForm(AccountPageForm):
            form_id = 'test-form'

        class MyPage(AccountPage):
            page_id = 'test-page'
            page_title = 'Test Page'

        register_account_page_class(MyPage)

        with self.assertRaises(ItemLookupError):
            MyPage.remove_form(MyForm)

    def test_default_form_classes_for_page(self):
        """Testing AccountPage._default_form_classes persistence"""
        class MyForm(AccountPageForm):
            form_id = 'test-form'

        class MyPage(AccountPage):
            page_id = 'test-page'
            page_title = 'Test Page'
            form_classes = [MyForm]

        register_account_page_class(MyPage)
        self.assertEqual(MyPage.form_classes, [MyForm])
        unregister_account_page_class(MyPage)
        self.assertEqual(MyPage.form_classes, [])
        register_account_page_class(MyPage)
        self.assertEqual(MyPage.form_classes, [MyForm])

    def test_empty_default_form_classes_for_page(self):
        """Testing AccountPage._default_form_classes with no form_classes"""
        class MyPage(AccountPage):
            page_id = 'test-page'
            page_title = 'Test Page'

        class MyForm(AccountPageForm):
            form_id = 'test-form'

        register_account_page_class(MyPage)
        self.assertEqual(MyPage.form_classes, [])
        MyPage.add_form(MyForm)
        self.assertEqual(MyPage.form_classes, [MyForm])
        unregister_account_page_class(MyPage)
        self.assertEqual(MyPage.form_classes, [])
        register_account_page_class(MyPage)
        self.assertEqual(MyPage.form_classes, [])


class UsernameTests(TestCase):
    """Unit tests for username rules."""

    cases = [
        ('spaces  ', 'spaces'),
        ('spa ces', 'spaces'),
        ('CASES', 'cases'),
        ('CaSeS', 'cases'),
        ('Spec!al', 'specal'),
        ('email@example.com', 'email@example.com'),
        ('da-shes', 'da-shes'),
        ('un_derscores', 'un_derscores'),
        ('mu ^lt&^ipl Es', 'multiples'),
    ]

    def test(self):
        """Testing username regex for LDAP/AD backends."""
        for orig, new in self.cases:
            self.assertEqual(
                re.sub(INVALID_USERNAME_CHAR_REGEX, '', orig).lower(),
                new)


class TrophyTests(TestCase):
    """Test the Trophy Case."""

    fixtures = ['test_users']

    def test_is_fish_trophy_awarded_for_new_review_request(self):
        """Testing if a fish trophy is awarded for a new review request."""
        user1 = User.objects.get(username='doc')
        category = 'fish'
        review_request = self.create_review_request(publish=True, id=3223,
                                                    submitter=user1)
        trophies = Trophy.objects.get_trophies(review_request)
        self.assertEqual(trophies[0].category, category)
        self.assertTrue(
            trophies[0].review_request.extra_data['calculated_trophies'])

    def test_is_fish_trophy_awarded_for_older_review_request(self):
        """Testing if a fish trophy is awarded for an older review request."""
        user1 = User.objects.get(username='doc')
        category = 'fish'
        review_request = self.create_review_request(publish=True, id=1001,
                                                    submitter=user1)
        del review_request.extra_data['calculated_trophies']
        trophies = Trophy.objects.get_trophies(review_request)
        self.assertEqual(trophies[0].category, category)
        self.assertTrue(
            trophies[0].review_request.extra_data['calculated_trophies'])

    def test_is_milestone_trophy_awarded_for_new_review_request(self):
        """Testing if a milestone trophy is awarded for a new review request.
        """
        user1 = User.objects.get(username='doc')
        category = 'milestone'
        review_request = self.create_review_request(publish=True, id=1000,
                                                    submitter=user1)
        trophies = Trophy.objects.compute_trophies(review_request)
        self.assertEqual(trophies[0].category, category)
        self.assertTrue(
            trophies[0].review_request.extra_data['calculated_trophies'])

    def test_is_milestone_trophy_awarded_for_older_review_request(self):
        """Testing if a milestone trophy is awarded for an older review
        request.
        """
        user1 = User.objects.get(username='doc')
        category = 'milestone'
        review_request = self.create_review_request(publish=True, id=10000,
                                                    submitter=user1)
        del review_request.extra_data['calculated_trophies']
        trophies = Trophy.objects.compute_trophies(review_request)
        self.assertEqual(trophies[0].category, category)
        self.assertTrue(
            trophies[0].review_request.extra_data['calculated_trophies'])

    def test_is_no_trophy_awarded(self):
        """Testing if no trophy is awarded."""
        user1 = User.objects.get(username='doc')
        review_request = self.create_review_request(publish=True, id=999,
                                                    submitter=user1)
        trophies = Trophy.objects.compute_trophies(review_request)
        self.assertFalse(trophies)


class SandboxAuthBackend(AuthBackend):
    """Mock authentication backend to test extension sandboxing."""

    backend_id = 'test-id'
    name = 'test'
    supports_change_name = True
    supports_change_email = True
    supports_change_password = True

    def authenticate(self, username, password):
        """Raise an exception to test sandboxing."""
        raise Exception

    def update_password(self, user, password):
        """Raise an exception to test sandboxing."""
        raise Exception

    def update_name(self, user):
        """Raise an exception to test sandboxing."""
        raise Exception

    def update_email(self, user):
        """Raise an exception to test sandboxing."""
        raise Exception


class SandboxTests(SpyAgency, TestCase):
    """Test extension sandboxing."""

    def setUp(self):
        """Initialize this test case."""
        super(SandboxTests, self).setUp()

        self.factory = RequestFactory()
        self.request = self.factory.get('test')
        self.user = User.objects.create_user(username='reviewboard', email='',
                                             password='password')
        self.profile = Profile.objects.get_or_create(user=self.user)
        self.spy_on(get_enabled_auth_backends,
                    call_fake=lambda: [SandboxAuthBackend()])

        # Suppresses MessageFailure Exception at the end of save()
        self.spy_on(messages.add_message,
                    call_fake=lambda x, y, z: None)

    def tearDown(self):
        """Uninitialize this test case."""
        super(SandboxTests, self).tearDown()

    def test_authenticate_auth_backend(self):
        """Testing sandboxing of AuthBackend.authenticate."""
        form = ChangePasswordForm(page=None, request=self.request,
                                  user=self.user)
        form.cleaned_data = {
            'old_password': self.user.password,
        }

        self.spy_on(SandboxAuthBackend.authenticate)

        self.assertRaisesMessage(
            ValidationError,
            'Unexpected error when validating the password. '
            'Please contact the administrator.',
            lambda: form.clean_old_password())
        self.assertTrue(SandboxAuthBackend.authenticate.called)

    def test_update_password_auth_backend(self):
        """Testing sandboxing of AuthBackend.update_password."""
        form = ChangePasswordForm(page=None, request=self.request,
                                  user=self.user)
        form.cleaned_data = {
            'old_password': self.user.password,
            'password1': 'password1',
            'password2': 'password1',
        }

        self.spy_on(SandboxAuthBackend.update_password)

        form.save()
        self.assertTrue(SandboxAuthBackend.update_password.called)

    def test_update_name_auth_backend(self):
        """Testing sandboxing of AuthBackend.update_name."""
        form = ProfileForm(page=None, request=self.request, user=self.user)
        form.cleaned_data = {
            'first_name': 'Barry',
            'last_name': 'Allen',
            'email': 'flash@example.com',
            'profile_private': '',
        }
        self.user.email = 'flash@example.com'

        self.spy_on(SandboxAuthBackend.update_name)

        form.save()
        self.assertTrue(SandboxAuthBackend.update_name.called)

    def test_update_email_auth_backend(self):
        """Testing sandboxing of AuthBackend.update_email."""
        form = ProfileForm(page=None, request=self.request, user=self.user)
        form.cleaned_data = {
            'first_name': 'Barry',
            'last_name': 'Allen',
            'email': 'flash@example.com',
            'profile_private': '',
        }
        self.user.first_name = 'Barry'
        self.user.last_name = 'Allen'

        self.spy_on(SandboxAuthBackend.update_email)

        form.save()
        self.assertTrue(SandboxAuthBackend.update_email.called)
