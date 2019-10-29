
import os,sys
import re
import shutil
import inspect
import subprocess
#import paramiko
import logging
import posixpath
import socket

from pprint import pformat as pp

try:
    import simplejson as json
except ImportError:
    import json
    
import datetime
import distutils.dir_util as dir_util

from gtcfg.pkg import BasePkg
from gtcfg.cfg import PkgCfg
import gtcfg.cfg

class PkgEnvError(BaseException):
    pass

class PkgInitError(BaseException):
    pass

class PkgVersionError(BaseException):
    pass

class PkgPublishError(BaseException):
    pass


class RepoPkgEnvError(BaseException):
    pass

class RepoPkgInitError(BaseException):
    pass

class RepoPkgVersionError(BaseException):
    pass


loglevel = logging.INFO
if os.environ.get('__DEBUG_',"False") == "True":   
    loglevel = logging.DEBUG
    
#KomodoIDE Remote Debugging
remote_brk = lambda: sys.stdout.write("remote break")
if os.environ.get("_REMOTE_DEBUG_",'False') == 'True':
    try:
        from dbgp.client import brk
        remote_brk = lambda: brk(host=os.environ.get("REMOTE_DEBUG_HOST","127.0.0.1"),
                                 port=int(os.environ.get("REMOTE_DEBUG_PORT",'9000')))
    except:
        pass
    
logging.basicConfig(level=loglevel)
LOG = logging.getLogger(__name__)

class RepoTag(object):
    _config_fields = []
    def __init__(self, **kw):
        self.id = kw.get("id", None)
        self.commit = kw.get("commit", None)
        self.name = kw.get("name", None)
        self.notes = kw.get("notes", None)
        self.path = kw.get("path", None)
        self.branch = kw.get("branch", None)
    
    def dump(self):
        data = self.__dict__.copy()
        if self._config_fields:
            _skip = set(data.keys()) - set(self._config_fields)
            for attr in _skip:
                data.pop(attr)
        
        return data
               

class RepoUser(object):
    _config_fields = []
    def __init__(self):
        self.login = os.environ.get("USERNAME",os.environ.get("USER"))
        self.home = os.environ.get("USERPROFILE",os.environ.get("HOME")).replace('\\','/')
        self.ssh_key = posixpath.join(self.home,".ssh","id_rsa.pub").replace("\\","/")
        self.hostname = socket.gethostname()
        self.ip = socket.gethostbyname(self.hostname)
    
    def dump(self):
        data = self.__dict__.copy()
        if self._config_fields:
            _skip = set(data.keys()) - set(self._config_fields)
            for attr in _skip:
                data.pop(attr)
        
        return data    


class Pkg(BasePkg):
    '''
    Class to manage deployment packages
    name=<package_name>
    '''
    _required_env = ("GT_BUILD_ROOT", "GT_DEV_ROOT")
    _valid_build = re.compile(r"^rc(\d+?)")
    _config_fields = ['name','version','root','platform','type']
    _buildlog = "buildlog.json"
    _release_notes = "release_notes.json"
    def __init__(self, **kw):
        super(Pkg, self).__init__(**kw)
        for evar in Pkg._required_env:
            try:
                os.environ[evar]
            except Exception as err:
                raise PkgEnvError("Required environment variable [{}] not found!!".format(evar))
        self._build_tags = []
        self._version_tags = []

    def _get_next_tag(self, release_type=None):
        if not release_type:
            return RepoTag(name="rc{}".format(str(int(self.build_tag.name.split("rc")[-1])+1)).zfill(3))

        major,minor,bug = self.version_tag.name.split(".")
        major = int(major)
        minor = int(minor)
        bug = int(bug)
        if release_type == 'major':
            major += 1
            minor = 0
            bug = 0
        elif release_type == 'minor':
            minor += 1
            bug = 0
        elif release_type == 'bug':
            bug += 1
            
        return RepoTag(name="{}.{}.{}".format(major,minor,bug))
    
    def _get_tag_commit(self, tag):
        """
        read it off filesystem
        """
        build_path = posixpath.join(self.build_root, tag.name, self._buildlog)
        try:
            data={}
            with open(build_path) as bfile:
                data = json.load(bfile)
                tag.commit = data['RepoTag']['commit']
        except:
            pass
        
    def _get_tags(self, builds=False, force=False):
        '''
        '''
        results = []
        try:
            if builds:
                tags = self.builds
            else:
                tags = self.versions
                
            for tag_ref in tags:
                tag = RepoTag(**{'name': tag_ref})
                self._get_tag_commit(tag)
                tag.path = posixpath.join(self.deploy_root,tag.name)
                if builds:    
                    tag.path = posixpath.join(self.build_root,tag.name)
                results.append(tag)
            
            if builds:
                self._build_tags = results
            else:
                self._version_tags = results
                
            return results
        
        except Exception as e:
            LOG.exception("Unable to get tags for [{}] >> {}\n".format(self.name,e))
            raise e
    
    @property
    def local_root(self):
        return posixpath.join(os.environ.get("GT_DEV_ROOT","./"), self.name)
    
    @property
    def build_root(self):
        pkg_path = os.environ.get("GT_BUILD_ROOT")
        if self.root == 'dev':
            pkg_path = posixpath.join(self._root_map.get(self.root), 'builds')
        pkg_path = posixpath.join(pkg_path,self.name)
        if self.platform:
            pkg_path = posixpath.join(pkg_path, platform.system.lower())
        return os.path.normpath(pkg_path)
 
    @property
    def versions(self):
        '''
        need caching
        '''
        results = []
        v_regex = re.compile(r'^(\d+?.\d+?.\d+?)')
        if os.path.exists(self.deploy_root):
            path_list = os.listdir(self.deploy_root)
            for item in os.listdir(self.deploy_root):
                path = posixpath.join(self.deploy_root, item)
                if os.path.isdir(path):
                    match = self._valid_version.match(item)
                    if match:
                        results.append(item)
        
        results.sort(key=lambda v: [int(n) for n in v.split('.')])
        
        return results
    
    @property
    def builds(self):
        results = []
        if os.path.exists(self.build_root):
            path_list = os.listdir(self.build_root)
            for item in os.listdir(self.build_root):
                path = posixpath.join(self.build_root, item)
                if os.path.isdir(path):
                    match = self._valid_build.match(item)
                    if match:
                        results.append(item)
        
        results.sort(key=lambda x: int(x.split('rc')[-1]))
        
        return results
    
    @property
    def build_tag(self):
        result = None
        if self.build_tags:
            result = self.build_tags[-1]
        else:
            result = RepoTag(name="rc0")
        return result
        
    @property
    def version_tag(self):
        result = None
        if self.version_tags:
            result = self.version_tags[-1]
        else:
            result = RepoTag(name="1.0.0")
        return result
    
    @property
    def version_tags(self):
        self._version_tags = self._get_tags()
        return self._version_tags
    
    @property
    def build_tags(self):
        self._build_tags = self._get_tags(builds=True)
        return self._build_tags
    
    def create_build_log(self, **kw):
        user = kw.get('user') or RepoUser()
        tag = kw.get('tag', {})
        log = {'date': datetime.datetime.now().strftime("%y/%m/%d-%H:%M"),
               'user': user.dump(),
               'tag': tag.dump(),
               'pkg': self.dump() }
        if kw.get('dump',False):
            with open(posixpath.join(tag.path, self._buildlog),'w') as bfile:
                json.dump(log, bfile, indent=4)
                
        return log
    
    
    def create_release_notes(self, build_log, **kw):
        """
        """
        notes = "\n===== [{}][{}] Release Notes =====\n".format(build_log['pkg']['name'], build_log['pkg']['version'])
        notes += "Notes: \n{}\n\n".format(kw.get('notes'))
        path = os.path.join(self.deploy_root)
        if self.root != 'cfg':
            path = os.path.join(self.deploy_root, self.version)
        with open(posixpath.join(tag.path, self._release_notes),'w') as bfile:
                notes += pp(build_log)
                bfile.write(notes)
                
        if kw.get('release',False):
            log_name = self._release_notes
            
            
    def build_release(self, **kw):
        '''
        stub w/o unit testing
        '''
        tag = self._get_next_tag()
        tag.path = posixpath.join(self.build_root, tag.name)
        if os.path.exists(tag.path) and kw.get('force',None):
            shutil.rmtree(tag.path)
        shutil.copytree(self.local_root, tag.path,
                        ignore=lambda directory, contents: ['.git'] if directory == self.local_root else [])
        return self.create_build_log(tag=tag, dump=True)
       
    def deploy_release(self,release,**kw):
        '''
        stub copy package from build root to deploy root
        '''
        #whatever branch you're on just put it on network
        #leave it to user to update repo
        deploy_ignore = ['.git','.pyc','.gitignore']
        build_log = self.build_release()
        build_tag = RepoTag(**build_log['tag'])
        tag = self._get_next_tag(release)
        tag.commit = build_tag.commit
        tag.path = posixpath.join(self.deploy_root, tag.name).replace('\\','/')
        self.version = tag.name
        
        if os.path.exists(tag.path) and kw.get('force',False):
            shutil.rmtree(tag.path)
        shutil.copytree(build_tag.path, tag.path,
                        ignore=lambda directory, contents: deploy_ignore if directory == build_tag.path else [])
        
        return self.create_build_log(tag=tag, dump=True)
    
    
    def publish(self, version, **kw):
        '''
        update targeted config 
        '''
        remote_brk()
        
        version_path = os.path.join(self.deploy_root,version)
        if not os.path.exists(version_path):
            LOG.warn("[{}] [{}] does not exist..".format(self.name, version))
            return
        
        project = kw.get('project_code','default')
        if self.root == 'cfg':
            project = 'default'
        
        
        _cfg_list = gtcfg.cfg.get_configs('pkg')
        _CfgChain = gtcfg.cfg.CfgChain(cfg_type='pkg', cfg_list=_cfg_list)
        _PkgCfg = _CfgChain.find_one(value=project)
        
        if not _PkgCfg:
            #creste new one
            #should validate against shotgun
            _cfg_list.sort(key=lambda cfg: int(cfg.id))
            next_cfg_id = int(_cfg_list[-1].id)+1
            _PkgCfg = gtcfg.cfg.init_cfg({"type":'pkg','id':next_cfg_id,'code':project.lower()})
        
        try:
            build_log_path = os.path.join(version_path, self._buildlog)
            if os.path.exists(build_log_path):    
                with open(build_log_path) as bfile:
                    build_log = json.load(build_log_path)
                    self.create_release_notes(build_log,**kw)
            
            if self.root =='cfg':
                dst = os.environ[self._root_map.get(self.root)]
                dir_util.copy_tree(version_path, dst)
                if os.path.exists(os.path.join(dst, self._buildlog)):
                    os.remove(os.path.join(dst, self._buildlog))
            #update config        
            pub_pkg = BasePkg(**self.dump())
            pub_pkg.version = version
            _PkgCfg.upsert(pub_pkg.dump())
            _PkgCfg.dump()
            
        except Exception as err:
            raise PkgPublishError(err)

            
class RepoPkg(Pkg):
    """
    Class to manage deployment package repos
    name=<package_name>
    """
    _required_env = ("GT_REPO_SERVER", "GT_REPO_ROOT")
    def __init__(self, **kw):
        super(RepoPkg, self).__init__(**kw)
        for evar in RepoPkg._required_env:
            try:
                os.environ[evar]
            except Exception as err:
                raise RepoPkgEnvError("Required environment variable [{}] not found!!".format(evar))
        self.user = RepoUser()
        self._repo_server = os.environ["GT_REPO_SERVER"]
        self._repo_root = os.environ["GT_REPO_ROOT"]
        self._init_repo()
            
    def _init_git(self, **kw):
        """
        attempt to run a git status to see if git is installed
        """
        try:
            proc = subprocess.Popen("git", shell=True, stderr=subprocess.PIPE,
                                    stdout=subprocess.PIPE)
            out, err = proc.communicate()
            exit_status = proc.returncode
            msg = "[git]: \n"
            if err:
                msg += err
            if out:
                msg += out
            if exit_status and err:
                msg += " "+str(err)+"\n"
                raise Exception(msg)
        except Exception as e:
    
            sys.stderr.write(str(e))
            raise Exception
      
    def _init_origin(self):
        pass
    
    def _init_repo(self, **kw):
        """
        assumes git is installed on system and ssh key is present
    
        repo_name = <name of repo to fetch>
        version = <version to search for>
        server = <git server>
        user = <git username>
        clone_path =  <path to clone to>
        """
        
        try:
            self._init_git()
            if not os.path.exists(self.local_root):
                self.clone()
            elif not self._is_repo():
                if kw.get('force',False):
                    shutil.rmtree(local_repo_path)
                    self.clone()
                else:
                    raise Exception("[{}] is not a valid repo!\n".format(self.local_root))
            else:
                self.fetch_changes()
        
        except Exception as err:
            raise RepoPkgInitError(err)
        
    def _is_repo(self, **kw):
        """
        """
        try:
            result = True
            msg = "[git status]: \n"
            os.chdir(self.local_root)
            proc = subprocess.Popen("git status",
                                  shell=True,
                                  stderr=subprocess.PIPE,
                                  stdout=subprocess.PIPE)
            out, err = proc.communicate()
            exit_status = proc.returncode
            if err:
                msg += err
            if out:
                msg += out
            if exit_status:
                result = False
                
        except Exception:
            sys.stderr.write(msg)
            raise
    
        return result
    
    def _is_dev_repo(self, **kw):
        '''
        log in to git server and return a list of repo names
        '''
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            try:
                client.connect(self._repo_server, username=self.user.login, password='', key_filename=self.user.ssh_key)
            except (paramiko.AuthenticationException,paramiko.SSHException) as message:
                raise Exception("[{}] >> ".format(self._repo_server, message))
            (stdin, stdout, ssh_stderr) = client.exec_command("ls {} | grep .git | cut -d '.' -f 1 ").format(self._repo_root)
            results = [l.rstrip() for l in stdout.readlines()]
            stdin.flush()
            client.close()
        except Exception as err:
            raise PkgServerError("[{}] >> {}".format(self._repo_server,err))

        return results
    
    def _get_tag_commit(self, tag, **kw):
        '''
        '''
        commit_id = None
        try:
            os.chdir(self.local_root)
            proc = subprocess.Popen("git rev-list -1 "+tag.id,
                                  shell=True,
                                  stderr=subprocess.PIPE,
                                  stdout=subprocess.PIPE)
            out, err = proc.communicate()
            exit_status = proc.returncode
            msg = "[git rev-list -1]: \n"
            commit_id = out.split("\n")[0]
            if err:
                msg += err
            if out:
                msg += out
            if exit_status:
                raise Exception(msg)
            tag.commit = commit_id
        except Exception as e:
            msg = "Unable to access [{}]: >> {}".format(self.name,e)
            sys.stderr.write(msg)
            raise e
    
    def _get_tags(self, builds=False,force=False):
        if not os.path.exists(self.local_root):
            return
        results = []
        try:
            if builds:
                #tag_regx = re.compile(r"^rc\d+?$")
                tag_regx = re.compile(r"^(\S+?)\s+\S+/(rc\d+)$")
                if self._build_tags and not force:
                    return self._build_tags
            else:
                if self._version_tags and not force:
                    return self._version_tags
                #tag_regx = re.compile(r"^\d+?.\d+?.\d+?$")
                tag_regx = re.compile(r"^(\S+)\s+\S+/(\d+?\.\d+?\.\d+?)$")
            proc = subprocess.Popen("git ls-remote --tags {}".format(self.server_root),
                                  shell=True,
                                  stderr=subprocess.PIPE,
                                  stdout=subprocess.PIPE)
            out, err = proc.communicate()
            exit_status = proc.returncode
            tags = out.split("\n")
            for tag_ref in tags:
                #tag = tag_ref.split("/")[-1]
                match = tag_regx.match(tag_ref)
                if match:
                    tag = RepoTag(**{'name': match.group(2), 'id': match.group(1)})
                    self._get_tag_commit(tag, **kw)
                    results.append(tag)
            msg = "[git tag]: \n"
            if err:
                msg += err
            if out:
                msg += out
            if exit_status:
                raise Exception(msg)
            
            results.sort(key=lambda t: [int(u) for u in t.id.split('.')])
            
            if builds:
                self._build_tags = results
            else:
                self._version_tags = results
                
            return results
        except Exception as e:
            msg = "Unable to access [{}] >> {}\n".format(self.name,e)
            sys.stderr.write(msg)
            raise e
           
    def fetch_changes(self, **kw):
        try:
            os.chdir(self.local_root)
            proc = subprocess.Popen("git fetch --all --tags",
                                  shell=True,
                                  stderr=subprocess.PIPE,
                                  stdout=subprocess.PIPE)
            out, err = proc.communicate()
            exit_status = proc.returncode
            msg = "[git fetch]: "
            if err:
                result=True
                msg += err
            if out:
                msg += out
            if exit_status:
                raise Exception
        
        except Exception as e:
            sys.stderr.write(str(e))
            raise e
        
    def clone(self, **kw):
        '''
        '''
        path = kw.get('path', os.path.dirname(self.local_root))
        branch = kw.get('branch', None) or self.current_branch
        
        try:
            os.chdir(path)
            server_path = self.server_root
            cmd = "git clone -b {} {}".format(branch, self.server_root)
            if not branch or branch == 'master':
                cmd = "git clone {}".format(self.server_root)
            proc =subprocess.Popen(cmd,
                shell=True,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE)
            err, out = proc.communicate()
            exit_status = proc.returncode
            msg= "[git clone]: \n"
            if err:
                msg+=err
            if out:
                msg+=out
            if exit_status:
                raise Exception(msg)
        except Exception as e:
            sys.stderr.write(str(e))
            raise e
        
    def push_changes(self, **kw):
        try:
            os.chdir(self.local_root)
            proc = subprocess.Popen("git push -f origin --tags --quiet",
                                  shell=True,
                                  stderr=subprocess.PIPE,
                                  stdout=subprocess.PIPE)
            err, out = proc.communicate()
            exit_status = proc.returncode
            msg = "[git push]: \n"
            if err:
                msg += err
            if out:
                msg += out
            if exit_status:
                raise Exception(msg)
        except Exception as e:
            sys.stderr.write(str(e))
            raise e

    def stage_changes(self, **kw):
        '''
        '''
        try:
            os.chdir(self.local_root)
            proc = subprocess.Popen("git add .",
                                  shell=True,
                                  stderr=subprocess.PIPE,
                                  stdout=subprocess.PIPE)
            out, err = proc.communicate()
            exit_status = proc.returncode
            msg = "[git add]: \n"
            if err:
                msg += err
            if out:
                msg += out
            if exit_status:
                raise Exception(msg)
            
        except Exception as e:
            sys.stderr.write(str(e))
            raise e
        
    def commit_changes(self, **kw):
        '''
        '''
        try:
            self.add(kw)
            message = kw.get('message','auto-commit')
            os.chdir(self.local_root)
            proc = subprocess.Popen("git commit -am \"{}\" --quiet".format(message),
                                  shell=True,
                                  stderr=subprocess.PIPE,
                                  stdout=subprocess.PIPE)
            out, err = proc.communicate()
            exit_status = proc.returncode
            msg = "[git commit]: \n"
            if err:
                msg += err
            if out:
                msg += out
            if exit_status:
                if "git push" in msg or "up-to-date" in msg or "nothing to commit" in msg:
                    pass
                else:
                    raise Exception(msg)
        except Exception as e:
            sys.stderr.write(str(e))
            raise e
            
    def create_version(self,release_type="minor"):
        '''
        tag current commit
        
        '''
        if self.current_branch == 'master':
            LOG.error("Versioning [{}] branch is prohibited".format(self.current_branch))
            return
        version = self.get_next_version(release_type)
        return version

    @property
    def server_root(self):
        return "{}:{}.git".format(self._repo_server,posixpath.join(self._repo_root,self.name))

    @property
    def current_branch(self):
        if not os.path.exists(self.local_root):
            return 'master'
        result = None
        msg = "[git status -s -b]: \n"
        try:
            os.chdir(self.local_root)
            proc = subprocess.Popen("git status -s -b",
                                  shell=True,
                                  stderr=subprocess.PIPE,
                                  stdout=subprocess.PIPE)
            out, err = proc.communicate()
            exit_status = proc.returncode
            if err:
                msg += err
            if out:
                msg += out
            if exit_status:
                raise Exception
            regex = re.compile(r"^## (.+)\b")
            match = regex.search(out.split("...")[0])
            if match:
                result = match.group(1).split(" ")[-1]

        except Exception:
            sys.stderr.write(msg)
            raise
    
        return result


def get_repo_packages():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    user = RepoUser()
    repo_root = "repos"
    results = []
    try:
        client.connect("git-server", username=user.login, password='jmistrot', key_filename=user.ssh_key)
        (stdin, stdout, ssh_stderr) = client.exec_command("ls "+repo_root+" | grep .git | cut -d '.' -f 1 ")
        results = [l.rstrip() for l in stdout.readlines()]
        stdin.flush()
        client.close()
    except (paramiko.AuthenticationException,paramiko.SSHException) as message:
        raise Exception("[{}] >> {} ".format("git-server", message))

    return results


def unittest():
    '''
    TODO: make real unittest :)
    '''
    import gtcfg.resolve
    import pprint
    env = gtcfg.resolve.environment()
    _pkg = gtcfg.resolve.packages(packages=["deployer"])[0]
    #_pkg = Pkg(name="deployer")
    print _pkg.path
    #result = _pkg.deploy_release()
    
    #print _pkg.path
    #pprint.pprint(_pkg.dump())
    
    

    #
    #
    #os.environ["GT_DEV_ROOT"] = "C:/Users/jean.mistrot/dev"
    #import gtcfg
    #gtcfg.resolve.environment()
    #PkgRepo(name="gtdevpkg")
    #
    
    
if __name__ == '__main__':
    unittest()
    