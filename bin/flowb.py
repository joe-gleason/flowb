#!/usr/bin/env python

import sys
import os
import json
import subprocess 
import re
import signal
from pprint import pprint
from time import ctime,sleep
from threading import Timer

PATHS         = {}
TASKS         = []
OPTS          = {}
STAGE_TIMER   = None
STAGE_TIMEOUT = False
GENERIC_ERROR = False

class Task():
    '''
    Holds the task information as well as the actual proc
    '''
    def __init__(self,p,**kwargs):
        
        # Take any keyword arguments and assign them to the dictionary
        for item in kwargs:
            self.__dict__[item] = kwargs[item]

        self.p           = p
        self.name_uniq   = "{}-{}".format(self.name,p.pid)
        self._timer      = None
        self.fail_reason = None

        if self.timeout_sec:
            self._timer_start(self.timeout_sec)

    def __getitem__(self,item):
        return getattr(self,item)

    def _task_timeout(self,**kwargs):
        info("** TASK TIMEOUT ** [{}]".format(self.name_uniq))
        self.fail_reason = "FAIL: Task timed out"
        self.p.kill()

    def _timer_start(self,timeout_sec):
        args = {}
        #info("Starting timer on proc [{}] for [{}] seconds".format(self.name_uniq,timeout_sec))
        self._timer = Timer(timeout_sec,self._task_timeout,[],args)
        self._timer.start()

    def kill(self):
        self.p.kill()
        if self._timer:
            self._timer.cancel();
            self._timer = None      
    
    def done(self):
        if self._timer:
            #info("Canceling timer on proc [{}]".format(self.name_uniq))
            self._timer.cancel();
            self._timer = None      

def stage_timeout(**kwargs):
    '''
    Timeout callback function.
    Registered with stage_timer_start
    '''
    global STAGE_TIMER
    global STAGE_TIMEOUT
    banner(" STAGE TIMEOUT EVENT ",char='%')
    STAGE_TIMEOUT=True

def stage_timer_start(timeout_sec):
    '''
    Start the stage timer
    '''
    global STAGE_TIMER
    global STAGE_TIMEOUT
    STAGE_TIMEOUT = False
    args = {}
    STAGE_TIMER = Timer(timeout_sec,stage_timeout,[],args)
    STAGE_TIMER.start()

def stage_timer_stop():
    '''
    Stop the stage timer
    '''
    global STAGE_TIMER
    global STAGE_TIMEOUT

    if STAGE_TIMER:
        STAGE_TIMER.cancel()
        STAGE_TIMER = None
    
    STAGE_TIMEOUT = False

def resolve_file(f,dirs=[],exts=[]):
    '''
    Resolve a file using potential directories and extensions
    '''
    path = None

    dirs.insert(0,".")
    exts.insert(0,"")

    if os.path.exists(f):
        # User provided explicit path
        path = os.path.realpath(f)
    else:
        # Search for the path
        for d in dirs:
            for ext in exts:
                path = "{}/{}{}".format(d,f,ext)
                if os.path.exists(path):
                    path = os.path.realpath(path)
                    break

    if path == None:
        sys.exit("Unable to resolve path for file [{}]".format(f))

    return path

def dir_create(d):
    '''
    Create a directory if it doesn't exist
    '''
    if not os.path.exists(d):
        os.mkdir(d)

def init():
    '''
    Initialize some globals
    '''
    global PATHS
    global OPTS

    PATHS['BIN_DIR']        = os.path.dirname(os.path.realpath(__file__))
    PATHS['TOOL_DIR']       = os.path.dirname(PATHS['BIN_DIR'])

    if OPTS['task_dir']:
        PATHS['TASKS_DIR']      = os.path.dirname(os.path.realpath(OPTS['task_dir']))
    else:
        PATHS['TASKS_DIR']      = "{}/tasks".format(PATHS['TOOL_DIR'])
        
    PATHS['FLOWS_DIR']      = "{}/flows".format(PATHS['TOOL_DIR'])
    PATHS['CONFIG_DIR']     = "{}/config".format(PATHS['TOOL_DIR'])
    
    PATHS['LAUNCH_DIR']     = os.getcwd()
    PATHS['RESULTS_DIR']    = "{}/results".format(PATHS['LAUNCH_DIR'])
    PATHS['OUTPUT_DIR']     = "{}/output".format(PATHS['RESULTS_DIR'])

    # Extend PYTHONPATH to include the root of the tool directory
    sys.path.append(PATHS['TOOL_DIR'])

    # No --flow_file provided on CLI
    # Let's try to resolve things before we error out
    if not OPTS['flow_file']:
        OPTS['flow_file'] = resolve_flow_file()

    if not OPTS['flow_file']:
        sys.exit("ERROR: No flow file (i.e. --flow_file) and unable to resolve based on project,branch,flow options")

    info("Establishing interrupt handler")
    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)
    signal.signal(signal.SIGHUP, sig_handler)

def resolve_flow_file():
    '''
    Resolve a flow file
    See if we can resolve the file based on project,branch,flow
    '''

    global OPTS
    
    from config.config import DATA

    project     = OPTS['project']
    branch      = OPTS['branch']
    flow        = OPTS['flow']
    flow_file   = None

    DATA = [x for x in DATA if x['project'].search(project)]
    DATA = [x for x in DATA if x['branch'].search(branch)]
    DATA = [x for x in DATA if x['flow'].search(flow)]
    
    if DATA:
        flow_file = DATA[0]['flow_file']

    return flow_file 

def div(msg=""):
    msg = "----- {}".format(msg)
    print(msg)    

def info(msg):
    #msg = "{} : {}".format(ctime(),msg)
    msg = "INFO : {}".format(msg)
    print(msg)    

def banner(msg,char='='):
    print('{}'.format(char)*40)
    print(msg)
    print('{}'.format(char)*40)

def wait_for_procs(kill_on_fail=False):
    '''
    Wait for Proc objects to finish.
    Optionally KILL remaining procs if 1 fails.
    '''

    global TASKS
    global STAGE_TIMEOUT
    global GENERAL_ERROR

    proc_results = {}

    info("Waiting for proc(s) to finish")

    # Helper functions
    def done(p):
        return p.poll() is not None
    def success(p):
        return p.returncode == 0

    
    while True:

        for task in TASKS:
            
            # Get the actual process opened by Popen(...
            p = task.p
            
            if STAGE_TIMEOUT or GENERIC_ERROR:

                # If the process isn't done - kill it and provide a reason
                if not done(p):
                    info("** KILL ** Task [{}]".format(task['name_uniq']))
                    proc_results[task.task_dir] = "FAIL: Killed due to a STAGE_TIMEOUT or GENERIC_ERROR"
                    task.kill()
                    sleep(1)

                elif 'FAIL' in proc_results.values():
                    # Any current failures in proc_results

                    if kill_on_fail: # Stage was configured to kill remaining tasks on failures

                        if 'FAIL' not in proc_results[task.task_dir]:
                            info("** KILL ** Task [{}]".format(task['name_uniq']))
                            proc_results[task.task_dir] = "FAIL: Killed because another task failed"
                            task.kill()

            if done(p): # Process Done

                # Turn off the timer if there is one
                # We don't want it to timeout accidentally
                task.done()

                # Flush the output file
                task.log_fh.flush()
                
                # Remove the ref from the list
                TASKS.remove(task)
                
                if success(p):
                    info("** PASS ** Task [{}]".format(task['name_uniq']))
                    proc_results[task.task_dir] = "PASS"
                else:

                    # Task timeouts provide their own reason
                    if task.fail_reason:
                        proc_results[task.task_dir] = task.fail_reason

                    # Task did not pass
                    # It may be marked with another state
                    # Only mark FAIL if it didn't finish for some other reason
                    if task.task_dir not in proc_results: # May have been marked as KILLED
                        info("** FAIL ** Task [{}]".format(task['name_uniq']))
                        proc_results[task.task_dir] = "FAIL"
                    
        if TASKS:            
            sleep(5)
        else:
            break
            
    return proc_results

def wait_for_procs_orig(kill_on_fail=False):
    '''
    Wait for Proc objects to finish.
    Optionally KILL remaining procs if 1 fails.
    '''

    global TASKS
    global STAGE_TIMEOUT
    global GENERAL_ERROR

    proc_results = {}

    info("Waiting for proc(s) to finish")

    # Helper functions
    def done(p):
        return p.poll() is not None
    def success(p):
        return p.returncode == 0

    
    while True:

        for task in TASKS:
            
            # Get the actual process opened by Popen(...
            p = task.p

            if done(p): # Process Done

                # Turn off the timer if there is one
                # We don't want it to timeout accidentally
                task.done()

                # Flush the output file
                task.log_fh.flush()
                
                # Remove the ref from the list
                TASKS.remove(task)
                
                if success(p):
                    print(STAGE_TIMEOUT)
                    info("** PASS ** Task [{}]".format(task['name_uniq']))
                    proc_results[task.task_dir] = "PASS"
                else:

                    # Task timeouts provide their own reason
                    if task.fail_reason:
                        proc_results[task.task_dir] = task.fail_reason

                    # Task did not pass
                    # It may be marked with another state
                    # Only mark FAIL if it didn't finish for some other reason
                    if task.task_dir not in proc_results: # May have been marked as KILLED
                        info("** FAIL ** Task [{}]".format(task['name_uniq']))
                        proc_results[task.task_dir] = "FAIL"
                    
        if TASKS:            
            # The stage may have timed out
            # Kill all tasks currently running
            if STAGE_TIMEOUT or GENERIC_ERROR:
                print("Hit a stage timeout")
                for task in TASKS:
                    p = task.p # Get the process (Popen(...))
                    # If the process isn't done - kill it and provide a reason
                    if not done(p):
                        info("** KILL ** Task [{}]".format(task['name_uniq']))
                        p.kill()
                        proc_results[task.task_dir] = "FAIL: Killed due to a STAGE_TIMEOUT or GENERIC_ERROR"
                        task.done() # task cleanup - timer cancel
                sleep(5)

            elif 'FAIL' in proc_results.values():
                # Any current failures in proc_results

                if kill_on_fail: # Stage was configured to kill remaining tasks on failures

                    for task in TASKS:
                        p = task.p
                        if not done(p):
                            info("** KILL ** Task [{}]".format(task['name_uniq']))
                            p.kill()
                            proc_results[task.task_dir] = "FAIL: Killed because another task failed"
                            task.done() # task cleanup - timer cancel
                    sleep(5)
            else:
                # Waiting for tasks to complete
                sleep(10) 
        else:
            # No more tasks remaining
            # Break from the while loop
            break
            
    return proc_results


def task_init(stage,task):
    '''
    Initialize a task
    '''
    global PATHS

    # DEFAULTS
    task_ref = {
        'name'             : None,
        'task'             : None,
        'task_opts'        : {},
        'stage_dir'        : stage['stage_dir'],
        'stage_dir_prev'   : stage['stage_dir_prev'],
        'stage_output_dir' : stage['stage_output_dir'],
        'timeout_sec'      : 0,
        'delay_begin_sec'  : 0,
        'delay_end_sec'    : 0,
        'task_src'         : None,
        'command'          : None,
        'PATHS'            : PATHS,
    }
    
    # Overrides
    for opt in task:
        task_ref[opt] = task[opt]

    # More config
    if task['task'] :
        task_ref['task_src']    = resolve_file(task['task'],dirs=[PATHS['TASKS_DIR']],exts=['.py','.pl','.sh'])

    task_ref['task_dir']    = "{}/{}".format(stage['stage_dir'],task_ref['name'])
    task_ref['config_file'] = "{}/config.json".format(task_ref['task_dir'])
    task_ref['log_file']    = "{}/output.log".format(task_ref['task_dir'])

    return task_ref

def stage_init(stage):
    ''' 
    Initialize a stage
    '''

    # DEFAULTS
    stage_ref = {
        'name'                  : None,
        'serial'                : False,
        'tasks'                 : [],
        'task_continue_on_fail' : False,
        'stage_continue_on_fail': False,
        'timeout_sec'           : 0,
    }
    
    # Override any defaults 
    for opt in stage:
        stage_ref[opt] = stage[opt]

    # More configuration
    stage_ref['stage_dir']          = "{}/{}".format(PATHS['RESULTS_DIR'],stage['name'])
    stage_ref['config_file']        = "{}/config.json".format(stage_ref['stage_dir'])
    stage_ref['stage_output_dir']   = "{}/output".format(stage_ref['stage_dir'])

    return stage_ref

def stage_run(stage):
    '''
    Run a particular stage
    '''

    global TASKS
    global OPTS
    global STAGE_TIMEOUT
    global GENERIC_ERROR

    def done(p):
        return p.poll() is not None
    def success(p):
        return p.returncode == 0

    banner("Stage [{}] START".format(stage['name']))
    pprint(stage)
    div()

    # Stage results (PASS|FAIL|KILLED) that get returned
    stage_proc_results = {}

    # Create the stage directory
    dir_create(stage['stage_dir'])
    dir_create(stage['stage_output_dir'])

    # Dump config file to stage directory
    with open(stage['config_file'],'w') as outfile:
        json.dump(stage,outfile,indent=4,sort_keys=True)       
    info("Stage config file [{}] written".format(stage['config_file']))

    # Current tasks in the stage
    tasks = stage['tasks']

    # Minimize the tasks if CLI options want to run specific tasks
    if OPTS['tasks']:
        tasks = [x for x in tasks if x['name'] in OPTS['tasks']]

    # See if we need to start a timer
    if stage['timeout_sec']:
        info("Starting stage timer for [{}] seconds".format(stage['timeout_sec']))
        stage_timer_start(stage['timeout_sec'])

    # Cycle through the tasks
    for task in tasks:

        if STAGE_TIMEOUT:
            break
        
        div() 

        # Initialize the task
        task = task_init(stage,task)
        dir_create(task['task_dir'])
        
        # Dump config file to task directory
        with open(task['config_file'],'w') as outfile:
            json.dump(task,outfile,indent=4,sort_keys=True)       
        info("Task config file [{}] written".format(task['config_file']))

        # Execute the task - task itself should be executable
        command = []

        # Start up delay
        if task['delay_begin_sec']:
            command.append("sleep {}".format(task['delay_begin_sec']))

        # The actual script to run
        if task['task_src']:
            command.append("{} {}".format(task['task_src'],task['config_file']))
        elif task['command']:
            command.append("{}".format(task['command']))
        else:
            GENERIC_ERROR = True
            print("ERROR: Task {} had neither 'task' or 'command' defined".format(task['name']))            
        
        # Start up delay
        if task['delay_end_sec']:
            command.append("sleep {}".format(task['delay_end_sec']))

                  
        #command = [task['task_src'],task['config_file']]
        command = ";".join(command)

        # Launch inside the task directory
        #   Also give the procedure a log_file to write to
        os.chdir(task['task_dir'])
        task_log_fh = open(task['log_file'],'w')
        p = subprocess.Popen(command,stdout=task_log_fh,stderr=task_log_fh,shell=True)
        task['log_fh'] = task_log_fh
        os.chdir(PATHS['RESULTS_DIR'])

        # Create PROC object
        # Add to global PROC list - used in wait_for_procs()
        proc_ref = Task(p,**task)
        TASKS.append(proc_ref)
        
        info("Command [{}]".format(command))
        info("Launched task [{}] in directory [{}]".format(proc_ref['name_uniq'],task['task_dir']))

        # Serial - Process PROC list immediately after adding
        if stage['serial'] == True:
           
            # Wait for procs, collect results
            results = wait_for_procs()

            # Add results to final tally
            for proc_name in results:
                stage_proc_results[proc_name] = results[proc_name]
        

            # When running in serial we decide whether a failure allows us to continue
            if not stage['task_continue_on_fail']:
                if 'FAIL' in stage_proc_results.values():
                    info("Configured to NOT continue on FAIL")
                    break
    
    # Parallel - Process after we have added all tasks
    if stage['serial'] == False: # Parallel
        
        div()

        # When running in parallel we decide whether a failure on 1 task kills the remaining
        kill_on_fail = not stage['task_continue_on_fail']
        results = wait_for_procs(kill_on_fail=kill_on_fail)

        # Add results to final tally
        for proc_name in results:
            stage_proc_results[proc_name] = results[proc_name]

    # There might not be any timer - but call it just in case
    stage_timer_stop()

    return stage_proc_results

def json_parse(f):
    '''
    Process a JSON file
    Remove comments #.*
    Replace Environment variables
    '''
   
    global OPTS

    fh = open(f,"r") 

    pattern = re.compile(r'\$\{(\w+)\}')

    lines = []
    for line in fh.readlines():
        # Replace environment variables
        line = line.rstrip()
        # Strip comments
        line = re.sub(r'#.*',"",line.rstrip())
        # replace environment variables
        searchObj = re.search(pattern,line)
        while searchObj:
            line = line.replace(searchObj.group(),os.environ[searchObj.group(1)])
            searchObj = re.search(pattern,line)
        lines.append(line)

    fh.close()

    if OPTS['debug']:
        for line in lines:
            print(line)

    json_data = json.loads("".join(lines))
    return json_data

def run(**kwargs):
    '''
    The main process that runs
    Run all stages
    '''
    global PATHS
    global OPTS
    global GENERIC_ERROR

    # Resulting exit code
    exit_code = 0

    # Assign CLI options to OPT dict
    for opt in kwargs:
        OPTS[opt] = kwargs[opt]

    # Initialize
    banner("Init")
    init()

    # Select config file
    json_file = resolve_file(OPTS['flow_file'],dirs=[PATHS['FLOWS_DIR']],exts=['.json'])
    json_parse(json_file)
    info("Pipeline file [{}]".format(json_file))
    stages = json_parse(json_file)

    # Create directories
    dir_create(PATHS['RESULTS_DIR'])
    dir_create(PATHS['OUTPUT_DIR'])
    
    # Setup some environment variables that tasks can use
    os.environ["FLOWB_RESULTS_DIR"] = PATHS['RESULTS_DIR']
    os.environ["FLOWB_OUTPUT_DIR"] = PATHS['OUTPUT_DIR']

    # Dump config file to results directory
    results_config = "{}/config.json".format(PATHS['RESULTS_DIR'])
    with open(results_config,'w') as outfile:
        json.dump(stages,outfile,indent=4,sort_keys=True)       
    
    # Only running a specific stages?
    #   Filter the stages variable to have just that stage
    if OPTS['stages']:
        stages = [x for x in stages if x['name'] in OPTS['stages']]

    # Looping information
    all_stage_results = {}
    stage_dir_prev  = None

    # Walk the flow
    for stage in stages:
        
        # Initialize stage 
        stage                   = stage_init(stage)
        stage['stage_dir_prev'] = stage_dir_prev

        # Run
        stage_results   = stage_run(stage)

        for proc_name in stage_results:
            all_stage_results[proc_name] = stage_results[proc_name]
            
        div()
        banner("Stage [{}] RESULTS".format(stage['name']))
        pprint(stage_results)
        
        info("Stage [{}] stage_continue_on_fail={}".format(stage['name'],stage['stage_continue_on_fail']))
       
        # FAIL found as substr in any process result
        if 'FAIL' in " ".join(stage_results.values()):
            if not stage['stage_continue_on_fail']:
                break

        if GENERIC_ERROR:
            print("Breaking due to GENERIC_ERROR")
            break

        # Keep track of previous stage
        stage_dir_prev = stage['stage_dir']

    # FAIL found as substr in any process result
    if 'FAIL' in " ".join(all_stage_results.values()):
        exit_code = 1

    banner("ALL STAGE RESULTS")
    pprint(all_stage_results)

    return exit_code

def sig_handler(signum,frame):
    global GENERIC_ERROR
    GENERIC_ERROR = True
    print("Signal handler called with signal {}".format(signum))
    print("Waiting for processes to fail...")


if __name__ == "__main__":
    
    import argparse

    parser = argparse.ArgumentParser(description="Run stages of tasks in serial or parallel")

    # Parse command line options
    parser.add_argument("-b","--branch",
                       action="store",
                       dest="branch",
                       default="",
                       help="The branch we are running on"
                       )
    parser.add_argument("-d","--debug",
                       action="store",
                       dest="debug",
                       default=0,
                       help="The branch we are running on"
                       )
    parser.add_argument("-f","--flow",
                       action="store",
                       dest="flow",
                       default="",
                       help="The flow to run"
                       )
    parser.add_argument("--flow_file",
                       action="store",
                       dest="flow_file",
                       default=None,
                       help="Provide a specific flow file to run.  Otherwise attempt to resolve based on -p,-b,-f options"
                       )
    parser.add_argument("-p","--project",
                       action="store",
                       dest="project",
                       default="",
                       help="The project to run"
                       )
    parser.add_argument("-s","--stage",
                       action="append",
                       dest="stages",
                       default=None,
                       help="The particular stage to run"
                       )
    parser.add_argument("-t","--task",
                       action="append",
                       dest="tasks",
                       default=None,
                       help="The particular task to run"
                       )
    parser.add_argument("-td","--task_dir",
                       action="store",
                       dest="task_dir",
                       default=None,
                       help="Task directory"
                       )

    args = parser.parse_args();

    sys.exit(run(**args.__dict__))
