import json
from django.core.cache import cache
                                            RepositoryError)
from reviewboard.scmtools.core import Branch, Commit
                                 '%(github_public_repo_name)s/'
                                 'issues#issue/%%s',
    supports_post_commit = True
    supports_repositories = True
    def check_repository(self, plan=None, *args, **kwargs):
        """Checks the validity of a repository.

        This will perform an API request against GitHub to get
        information on the repository. This will throw an exception if
        the repository was not found, and return cleanly if it was found.
        """
        try:
            repo_info = self._api_get_repository(
                self._get_repository_owner_raw(plan, kwargs),
                self._get_repository_name_raw(plan, kwargs))
        except Exception, e:
            if str(e) == 'Not Found':
                if plan in ('public', 'private'):
                    raise RepositoryError(
                        _('A repository with this name was not found, or your '
                          'user may not own it.'))
                elif plan == 'public-org':
                    raise RepositoryError(
                        _('A repository with this organization or name was not '
                          'found.'))
                elif plan == 'private-org':
                    raise RepositoryError(
                        _('A repository with this organization or name was '
                          'not found, or your user may not have access to '
                          'it.'))

            raise

        if 'private' in repo_info:
            is_private = repo_info['private']

            if is_private and plan in ('public', 'public-org'):
                raise RepositoryError(
                    _('This is a private repository, but you have selected '
                      'a public plan.'))
            elif not is_private and plan in ('private', 'private-org'):
                raise RepositoryError(
                    _('This is a public repository, but you have selected '
                      'a private plan.'))

                body=json.dumps(body))
                rsp = json.loads(data)
        url = self._build_api_url(self._get_repo_api_url(repository),
                                  'git/blobs/%s' % revision)
        url = self._build_api_url(self._get_repo_api_url(repository),
                                  'git/blobs/%s' % revision)
    def get_branches(self, repository):
        results = []
        url = self._build_api_url(self._get_repo_api_url(repository),
                                  'git/refs/heads')
        try:
            rsp = self._api_get(url)
        except Exception, e:
            logging.warning('Failed to fetch commits from %s: %s',
                            url, e)
            return results
        for ref in rsp:
            refname = ref['ref']
            if not refname.startswith('refs/heads/'):
                continue
            name = refname.split('/')[-1]
            results.append(Branch(name, ref['object']['sha'],
                                  default=(name == 'master')))
        return results
    def get_commits(self, repository, start=None):
        results = []
        resource = 'commits'
        url = self._build_api_url(self._get_repo_api_url(repository), resource)
        if start:
            url += '&sha=%s' % start
            rsp = self._api_get(url)
        except Exception, e:
            logging.warning('Failed to fetch commits from %s: %s',
                            url, e)
            return results

        for item in rsp:
            commit = Commit(
                item['commit']['author']['name'],
                item['sha'],
                item['commit']['committer']['date'],
                item['commit']['message'])
            if item['parents']:
                commit.parent = item['parents'][0]['sha']

            results.append(commit)

        return results

    def get_change(self, repository, revision):
        repo_api_url = self._get_repo_api_url(repository)

        # Step 1: fetch the commit itself that we want to review, to get
        # the parent SHA and the commit message. Hopefully this information
        # is still in cache so we don't have to fetch it again.
        commit = cache.get(repository.get_commit_cache_key(revision))
        if commit:
            author_name = commit.author_name
            date = commit.date
            parent_revision = commit.parent
            message = commit.message
        else:
            url = self._build_api_url(repo_api_url, 'commits')
            url += '&sha=%s' % revision
            commit = self._api_get(url)[0]
            author_name = commit['commit']['author']['name']
            date = commit['commit']['committer']['date'],
            parent_revision = commit['parents'][0]['sha']
            message = commit['commit']['message']
        # Step 2: fetch the "compare two commits" API to get the diff.
        url = self._build_api_url(
            repo_api_url, 'compare/%s...%s' % (parent_revision, revision))
        comparison = self._api_get(url)

        tree_sha = comparison['base_commit']['commit']['tree']['sha']
        files = comparison['files']

        # Step 3: fetch the tree for the original commit, so that we can get
        # full blob SHAs for each of the files in the diff.
        url = self._build_api_url(repo_api_url, 'git/trees/%s' % tree_sha)
        url += '&recursive=1'
        tree = self._api_get(url)

        file_shas = {}
        for file in tree['tree']:
            file_shas[file['path']] = file['sha']

        diff = []

        for file in files:
            filename = file['filename']
            status = file['status']
            patch = file['patch']

            diff.append('diff --git a/%s b/%s' % (filename, filename))

            if status == 'modified':
                old_sha = file_shas[filename]
                new_sha = file['sha']
                diff.append('index %s..%s 100644' % (old_sha, new_sha))
                diff.append('--- a/%s' % filename)
                diff.append('+++ b/%s' % filename)
            elif status == 'added':
                new_sha = file['sha']

                diff.append('new file mode 100644')
                diff.append('index %s..%s' % ('0' * 40, new_sha))
                diff.append('--- /dev/null')
                diff.append('+++ b/%s' % filename)
            elif status == 'removed':
                old_sha = file_shas[filename]

                diff.append('deleted file mode 100644')
                diff.append('index %s..%s' % (old_sha, '0' * 40))
                diff.append('--- a/%s' % filename)
                diff.append('+++ /dev/null')

            diff.append(patch)

        diff = '\n'.join(diff)

        # Make sure there's a trailing newline
        if not diff.endswith('\n'):
            diff += '\n'

        commit = Commit(author_name, revision, date, message, parent_revision)
        commit.diff = diff
        return commit
    def _build_api_url(self, *api_paths):
        return '%s?access_token=%s' % (
            '/'.join(api_paths),
        return self._get_repo_api_url_raw(
            self._get_repository_owner_raw(plan, repository.extra_data),
            self._get_repository_name_raw(plan, repository.extra_data))

    def _get_repo_api_url_raw(self, owner, repo_name):
        return '%srepos/%s/%s' % (self.get_api_url(self.account.hosting_url),
                                   owner, repo_name)

    def _get_repository_owner_raw(self, plan, extra_data):
            return self.account.username
            return self.get_plan_field(plan, extra_data, 'name')
    def _get_repository_name_raw(self, plan, extra_data):
        return self.get_plan_field(plan, extra_data, 'repo_name')

    def _api_get_repository(self, owner, repo_name):
        return self._api_get(self._build_api_url(
            self._get_repo_api_url_raw(owner, repo_name)))

    def _api_get(self, url):
        try:
            data, headers = self._http_get(url)
            return json.loads(data)
        except (urllib2.URLError, urllib2.HTTPError), e:
            data = e.read()

            try:
                rsp = json.loads(data)
            except:
                rsp = None

            if rsp and 'message' in rsp:
                raise Exception(rsp['message'])
            else:
                raise Exception(str(e))