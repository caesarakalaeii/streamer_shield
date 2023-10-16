import logging
import time
import os
has_ros = True
try:
    import rospy #checks if rospy is present
except ImportError:
            has_ros = False 


class Logger():
    def __init__(self, ros_log = False, console_log = False, file_logging = False, file_URI = None, level = logging.DEBUG, process_name = __name__, override = False):
        if has_ros:
            self.ros_log = ros_log
        else:
            self.ros_log = False #set Ros logging to false if rospy has not been detected
        
        self.console_log = console_log
        self.file_logging = file_logging
        if file_logging:
            if file_URI is None:
                for i in range(100):
                    if os.path.exists("log\\%s_log_%s_%d.log"%(process_name,time.localtime(),i)):
                        continue
                    file_URI = "log\\%s_log_%s_%d.log"%(process_name,time.localtime(),i)
                    
            else:
                if os.path.exists(file_URI) and not override:
                    raise NameError("Log File already exists! Try setting override flag")
                else:
                    if os.path.exists(file_URI) and override:
                        os.remove(file_URI)
                    self.file_URI = file_URI
            logging.basicConfig(filename=file_URI, level=level, format='%(asctime)s %(message)s')
            

    def warning(self, skk): #yellow
        
        if self.console_log:
            print("\033[93m {}\033[00m" .format("WARNING:"),"\033[93m {}\033[00m" .format(skk))
        if self.ros_log:
            rospy.logwarn(skk)
        if self.file_logging:
            logging.warning(skk)
       
    def error(self, skk): #red
        if self.console_log:   
            print("\033[91m {}\033[00m" .format("ERROR:"),"\033[91m {}\033[00m" .format(skk))
        if self.ros_log:
            rospy.logerr(skk)
        if self.file_logging:
            logging.error(skk)
        
    def fail(self, skk): #red
        if self.console_log: 
            print("\033[91m {}\033[00m" .format("FATAL:"),"\033[91m {}\033[00m" .format(skk))
        if self.ros_log:
            rospy.logfatal(skk)
        if self.file_logging:
            logging.exception(skk)
    def passing(self, skk): #green
        if self.console_log: 
            print("\033[92m {}\033[00m" .format(skk))
        if self.ros_log:
            rospy.loginfo(skk)
        if self.file_logging:
            logging.info(skk)
    def passingblue(self, skk): #blue
        if self.console_log: 
            print("\033[96m {}\033[00m" .format(skk))
        if self.ros_log:
            rospy.loginfo(skk)
        if self.file_logging:
            logging.info(skk)
    def info(self, skk): #blue
        if self.console_log: 
            print("\033[94m {}\033[00m" .format("Info:"),"\033[94m {}\033[00m" .format(skk))
        if self.ros_log:
            rospy.loginfo(skk)
        if self.file_logging:
            logging.debug(skk)