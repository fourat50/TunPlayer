import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tunplayer.parental import CategoryLocks,category_key,PinError


class CategoryProtection(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'parental.json'
        self.now=1000.;self.policy=CategoryLocks(self.path,clock=lambda:self.now)

    def tearDown(self):self.tmp.cleanup()

    def test_pin_uses_salted_scrypt_and_a_private_file(self):
        self.policy.set_pin('7391');data=json.loads(self.path.read_text())
        self.assertNotIn('"7391"',self.path.read_text());self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        self.assertEqual(len(bytes.fromhex(data['pin']['salt'])),16);self.assertEqual(len(bytes.fromhex(data['pin']['digest'])),32)
        first=self.policy.record.copy();self.policy.set_pin('7391',current='7391');self.assertNotEqual(first,self.policy.record)

    def test_pin_requires_four_to_eight_ascii_digits(self):
        for value in ('123','123456789','abcd','１２３４','12 34'):
            with self.subTest(value=value),self.assertRaises(PinError):self.policy.set_pin(value)
        self.assertFalse(self.policy.configured)

    def test_locked_category_is_case_insensitive_and_scoped_by_content_kind(self):
        self.policy.set_pin('7391');self.policy.protect('movie','Adulte','7391')
        self.assertTrue(self.policy.locked('movie','adulte'));self.assertFalse(self.policy.locked('live','Adulte'))

    def test_five_failed_attempts_trigger_a_persistent_cooldown(self):
        self.policy.set_pin('7391')
        for _ in range(5):self.assertFalse(self.policy.verify('0000'))
        self.assertEqual(self.policy.remaining(),30);self.assertFalse(self.policy.verify('7391'))
        restored=CategoryLocks(self.path,clock=lambda:self.now);self.assertEqual(restored.remaining(),30)
        self.now+=31;self.assertTrue(restored.verify('7391'));self.assertEqual(restored.failures,0)

    def test_session_grants_are_never_persisted(self):
        self.policy.set_pin('7391');self.policy.protect('series','Adulte','7391')
        key=category_key('series','Adulte');self.assertEqual(self.policy.pending({key}),{key})
        self.policy.grants.add(key);self.assertEqual(self.policy.pending({key}),set())
        restored=CategoryLocks(self.path);self.assertEqual(restored.pending({key}),{key})
        self.policy.relock();self.assertEqual(self.policy.pending({key}),{key})

    def test_modifying_pin_and_removing_a_lock_require_the_current_pin(self):
        self.policy.set_pin('7391');self.policy.protect('movie','Adulte','7391')
        with self.assertRaises(PinError):self.policy.set_pin('9876',current='0000')
        with self.assertRaises(PinError):self.policy.protect('movie','Adulte','0000',False)
        self.assertTrue(self.policy.locked('movie','Adulte'));self.assertTrue(self.policy.verify('7391'))
        self.policy.protect('movie','Adulte','7391',False);self.assertFalse(self.policy.locked('movie','Adulte'))

    def test_corrupt_policy_fails_closed(self):
        self.path.write_text('not-json');policy=CategoryLocks(self.path)
        self.assertTrue(policy.configured);self.assertTrue(policy.pending({category_key('movie','Films')}))
        self.assertFalse(policy.verify('7391'))

    def test_failed_save_does_not_replace_the_configured_pin_in_memory(self):
        self.policy.set_pin('7391');before=self.policy.record.copy()
        # Authentication may save counters; fail only the actual new-PIN commit.
        save=self.policy._save
        def fail_change():
            if self.policy.record!=before:raise PermissionError('disk unavailable')
            return save()
        with patch.object(self.policy,'_save',side_effect=fail_change):
            with self.assertRaises(PermissionError):self.policy.set_pin('9876',current='7391')
        self.assertEqual(self.policy.record,before);self.assertTrue(self.policy.verify('7391'))

    def test_nonfinite_cooldown_is_treated_as_a_corrupt_policy(self):
        self.path.write_text('{"blocked_until": NaN}')
        policy=CategoryLocks(self.path)
        self.assertTrue(policy.invalid);self.assertFalse(policy.verify('7391'))
