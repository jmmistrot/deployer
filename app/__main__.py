

if __name__ == '__main__':
    import os
    import argparse
    import logging
    from pprint import pprint as pp
    import gtcfg.resolve
    gtcfg.resolve.environment()
    
    parser = argparse.ArgumentParser(description='Deploy | Publish Packages via UI or command-line')
    group = parser.add_mutually_exclusive_group()
    parser.add_argument('-pkg','--package', help='The package name you want to deploy.')
    group.add_argument('-rel','--release', help='The release type (major,minor,bug).', choices=['major','minor','bug'])
    group.add_argument('-ver','--version', help='The package version to publish.')
    parser.add_argument('-prj','--project', help='The project to which to publish the package version.')
    parser.add_argument('--debug', action='store_true')
    
    args = parser.parse_args()
    action=None
    action_arg=None
    project = args.project
    
    loglevel = logging.INFO
    os.environ["_DEBUG_"]= "False"
    if args.debug:
        os.environ["_DEBUG_"]= "True"
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
    LOG = logging.getLogger("deployer")
    
    
        
        
    if not project:
        project = os.environ.get("PROJECT_NAME", "default")
    if args.version:
        action="publish"
        action_arg = args.version
    if args.release:
        action="deploy_release"
        action_arg = args.release
    
    if args.package and action and action_arg:
        import pkg
        _pkg_list = gtcfg.resolve.packages("default", packages=[args.package],user=False)
        if not _pkg_list:
            _Pkg = pkg.Pkg(name=args.package)
        else:
            _Pkg = pkg.Pkg(**_pkg_list[0].dump())
        func = "_Pkg.{}('{}', project_code='{}')".format(action, action_arg, project)
        print "====== [{}] {} {} ======\nComplete".format(args.package, action, action_arg)
        result = eval(func)
        if args.debug:
            pp(result)
        
    
    else:
        import app
        app.run(package=args.package,
                action=action,
                action_arg=action_arg,
                project=project)
        

    
        