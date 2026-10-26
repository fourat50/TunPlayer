import unittest
from unittest.mock import patch
from scripts import separate_github_repositories as separation


class RepositorySeparation(unittest.TestCase):
    def test_changed_source_is_never_deleted(self):
        with patch.object(separation,'remote_ref',return_value='different'),patch.object(separation,'run') as run:
            with self.assertRaises(RuntimeError):separation.archive_old_branch()
            run.assert_not_called()

    def test_unconfirmed_archive_is_never_deleted(self):
        with patch.object(separation,'remote_ref',side_effect=[separation.OLD_COMMIT,None,None]),patch.object(separation,'run') as run:
            with self.assertRaises(RuntimeError):separation.archive_old_branch()
            self.assertFalse(any(any(str(a).startswith('--force-with-lease') for a in c.args) for c in run.call_args_list))

    def test_archive_precedes_exact_lease_deletion(self):
        with patch.object(separation,'remote_ref',side_effect=[separation.OLD_COMMIT,None,separation.OLD_COMMIT]),patch.object(separation,'run') as run:
            separation.archive_old_branch()
            calls=run.call_args_list
            self.assertIn(separation.OLD_COMMIT+':refs/heads/archive/'+separation.OLD_BRANCH,calls[1].args)
            self.assertIn('--force-with-lease=refs/heads/'+separation.OLD_BRANCH+':'+separation.OLD_COMMIT,calls[2].args)
            self.assertEqual(calls[2].args[-1],':refs/heads/'+separation.OLD_BRANCH)

    def test_already_clean_is_noop(self):
        with patch.object(separation,'remote_ref',return_value=None),patch.object(separation,'run') as run:
            separation.archive_old_branch()
            run.assert_not_called()
