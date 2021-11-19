'''
Functions to serialize and send commands to an ABB IRC5- based robot. 
'''

import socket
import time
import inspect
from threading import Thread, Event
import logging

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())
    
_UNITS_L = {'millimeters': 1.0,
            'meters'     : 1000.0,
            'inches'     : 25.4}
_UNITS_A = {'degrees' : 1.0,
            'radians' : 57.2957795}
_ZONES = {'z0'  : [.3,.3,.03], 
          'z1'  : [1,1,.1], 
          'z5'  : [5,8,.8], 
          'z10' : [10,15,1.5], 
          'z15' : [15,23,2.3], 
          'z20' : [20,30,3], 
          'z30' : [30,45,4.5], 
          'z50' : [50,75,7.5], 
          'z100': [100,150,15], 
          'z200': [200,300,30]}
_DELAY = .08

class Robot:
    def __init__(self, 
                 ip          = '192.168.125.1', 
                 port_motion = 5000,
                 port_logger = 5001,
                 callback_log = None):

        # connect to the robot controller to start logging positions
        # and joint values
        self._stopped      = Event()
        self._callback_log = callback_log
        self._log_thread   = Thread( target = self.connect_logger,
                                     args   = ((ip, port_logger))).start()
        
        self._connect_motion((ip, port_motion))
        self.set_units('meters', 'radians') # ABB default units are mm/degrees
        self.set_tool()                     # set to center of tool flange
        self.set_workobject()               # set to center of base
        self.set_speed()                    # 100 mm/s            
        self.set_zone()                     # 1mm zone region

    def _connect_motion(self, remote):        
        log.info('Attempting to connect to robot motion server at %s', str(remote))
        self._sock = socket._socket(socket.AF_INET, socket._SOCK_STREAM)
        self._sock.settimeout(2.5)
        self._sock.connect(remote)
        self._sock.settimeout(None)
        log.info('Connected to robot motion server at %s', str(remote))

    def _connect_logger(self, remote):
        sock = socket._socket(socket.AF_INET, socket._SOCK_STREAM)
        sock.connect(remote)
        sock.setblocking(1)
        try:
            while not self._stopped.isset():
                result = {}
                data   = s.recv(4096).split()
                if int(data[1]) == 0: 
                    result['pose']   = map(float, data[4:])
                elif int(data[1]) == 1:
                    result['joints'] =  map(float, data[4:])
                if not self._callback_log is None:
                    self._callback_log(**result)
        finally:
            sock.shutdown(socket.SHUT_RDWR)

    def set_units(self, linear='meters', angular='radians'):
        self._scale_linear = _UNITS_L[linear]
        self._scale_angle  = _UNITS_A[angular]

    def set_cartesian(self, pose):
        '''
        Executes a move immediately from the current pose,
        to 'pose', with units of millimeters.
        '''
        msg  = "01 " + self._format_pose(pose)   
        return self._send(msg)

    def set_joints(self, joints):
        '''
        Executes a move immediately, from current joint angles,
        to 'joints', in degrees. 
        '''
        if len(joints) != 6: return False
        msg = "02 "
        for joint in joints: 
            msg += format(joint*self._scale_angle, "+08.2f") + " " 
        msg += "#" 
        return self._send(msg)

    def get_cartesian(self):
        '''
        Returns the current pose of the robot, in millimeters
        '''
        msg = "03 #"
        data = self._send(msg).split()
        r = [float(s) for s in data]
        return [r[2:5], r[5:9]]

    def get_joints(self):
        '''
        Returns the current angles of the robots joints, in degrees. 
        '''
        msg = "04 #"
        data = self._send(msg).split()
        return [float(s) / self._scale_angle for s in data[2:8]]

    def get_external_axis(self):
        '''
        If you have an external axis connected to your robot controller
        (such as a FlexLifter 600, google it), this returns the joint angles
        '''
        msg = "05 #"
        data = self._send(msg).split()
        return [float(s) for s in data[2:8]]
       
    def get_robotinfo(self):
        '''
        Returns a robot- unique string, with things such as the
        robot's model number. 
        Example output from and IRB 2400:
        ['24-53243', 'ROBOTWARE_5.12.1021.01', '2400/16 Type B']
        '''
        msg = "98 #"
        data = str(self._send(msg))[5:].split('*')
        log.debug('get_robotinfo result: %s', str(data))
        return data

    def set_tool(self, tool=[[0,0,0], [1,0,0,0]]):
        '''
        Sets the tool centerpoint (TCP) of the robot. 
        When you command a cartesian move, 
        it aligns the TCP frame with the requested frame.
        
        Offsets are from tool0, which is defined at the intersection of the
        tool flange center axis and the flange face.
        '''
        msg       = "06 " + self._format_pose(tool)    
        self._send(msg)
        self.tool = tool
        
    def get_tool(self): 
        log.debug('get_tool returning: %s', str(self.tool))
        return self.tool

    def set_workobject(self, work_obj=[[0,0,0],[1,0,0,0]]):
        '''
        The workobject is a local coordinate frame you can define on the robot,
        then subsequent cartesian moves will be in this coordinate frame. 
        '''
        msg = "07 " + self._format_pose(work_obj)   
        self._send(msg)

    def set_speed(self, speed=[100,50,50,50]):
        '''
        speed: [robot TCP linear speed (mm/s), TCP orientation speed (deg/s),
                external axis linear, external axis orientation]
        '''

        if len(speed) != 4: return False
        msg = "08 " 
        msg += format(speed[0], "+08.1f") + " " 
        msg += format(speed[1], "+08.2f") + " "  
        msg += format(speed[2], "+08.1f") + " " 
        msg += format(speed[3], "+08.2f") + " #"     
        self._send(msg)

    def set_zone(self, 
                 zone_key     = 'z1', 
                 point_motion = False, 
                 manual_zone  = None):
        '''
        Sets the motion zone of the robot. This can also be thought of as
        the flyby zone, AKA if the robot is going from point A -> B -> C,
        how close do we have to pass by B to get to C
        
        zone_key: uses values from RAPID handbook (stored here in zone_dict)
        with keys 'z*', you should probably use these

        point_motion: go to point exactly, and stop briefly before moving on

        manual_zone = [pzone_tcp, pzone_ori, zone_ori]
        pzone_tcp: mm, radius from goal where robot tool centerpoint 
                   is not rigidly constrained
        pzone_ori: mm, radius from goal where robot tool orientation 
                   is not rigidly constrained
        zone_ori: degrees, zone size for the tool reorientation
        '''

        if point_motion: 
            zone = [0,0,0]
        elif ((not manual_zone is None) and 
              len(manual_zone) == 3): 
            zone = manual_zone
        elif zone_key in _ZONES: 
            zone = _ZONES[zone_key]
        else: return False
        
        msg = "09 " 
        msg += str(int(point_motion)) + " "
        msg += format(zone[0], "+08.4f") + " " 
        msg += format(zone[1], "+08.4f") + " " 
        msg += format(zone[2], "+08.4f") + " #" 
        self._send(msg)

    def set_cartesian_buffer(self, pose_list):
        '''
        Adds every pose in pose_list to the remote buffer
        '''
        def buffer_add(pose):
            # add a cartesian pose to the IRC5
            msg = "30 " + self._format_pose(pose) 
            self._send(msg)
        def buffer_clear(self):
            # clear the buffer on the IRC5
            msg = "31 #"
            data = self._send(msg)
            if buffer_len() != 0:
                log.warn('clear_buffer failed! buffer_len: %i', 
                         self.buffer_len())
                raise NameError('clear_buffer failed!')
        def buffer_len(self):
            # find out the number of poses currently stored on the IRC5
            msg = "32 #"
            data = self._send(msg).split()
            return int(float(data[2]))

        buffer_clear()
        for pose in pose_list: 
            buffer_add(pose)
        if buffer_len() == len(pose_list):
            log.debug('Successfully added %i poses to remote buffer', 
                      len(pose_list))
            return True
        else:
            log.warn('Failed to add poses to remote buffer!')
            clear_buffer()
            return False

    def execute_cartesian_buffer(self):
        '''
        Immediately execute linear moves to every pose in the remote buffer.
        '''
        msg = "33 #"
        return self._send(msg)

    def set_external_axis(self, axis_unscaled=[-550,0,0,0,0,0]):
        if len(axis_values) != 6: return False
        msg = "34 "
        for axis in axis_values:
            msg += format(axis, "+08.2f") + " " 
        msg += "#"   
        return self._send(msg)

    def move_circular(self, pose_onarc, pose_end):
        '''
        Executes a movement in a circular path from current position, 
        through pose_onarc, to pose_end
        '''
        msg_0 = "35 " + self._format_pose(pose_onarc)  
        msg_1 = "36 " + self._format_pose(pose_end)

        data = self._send(msg_0).split()
        if data[1] != '1': 
            log.warn('move_circular incorrect response, bailing!')
            return False
        return self._send(msg_1)

    def set_dio(self, value, id=0):
        '''
        A function to set a physical DIO line on the robot.
        For this to work you're going to need to edit the RAPID function
        and fill in the DIO you want this to switch. 
        '''
        msg = '97 ' + str(int(bool(value))) + ' #'
        return self._send(msg)
        
    def send(self, message, wait_for_response=True):
        '''
        Send a formatted message to the robot socket.
        if wait_for_response, we wait for the response and return it
        '''
        caller = inspect.stack()[1][3]
        log.debug('%-14s sending: %s', caller, message)
        self._sock._send(message)
        time.sleep(_DELAY)
        if not wait_for_response: return
        data = self._sock.recv(4096)
        log.debug('%-14s recieved: %s', caller, data)
        return data
        
    def _format_pose(self, pose):
        pose = _check_coordinates(pose)
        msg  = ''
        for cartesian in pose[0]:
            msg += format(cartesian * self._scale_linear,  "+08.1f") + " " 
        for quaternion in pose[1]:
            msg += format(quaternion, "+08.5f") + " " 
        msg += "#" 
        return msg       
        
    def close(self):
        self._send("99 #", False)
        self._sock.shutdown(socket.SHUT_RDWR)
        self._sock.close()
        self._stopped.set()
        log.info('Disconnected from ABB robot.')

    def __enter__(self):
        return self
        
    def __exit__(self, type, value, traceback):
        self.close()

def _check_coordinates(coordinates):
    if ((len(coordinates) == 2) and
        (len(coordinates[0]) == 3) and 
        (len(coordinates[1]) == 4)): 
        return coordinates
    elif (len(coordinates) == 7):
        return [coordinates[0:3], coordinates[3:7]]
    log.warn('Recieved malformed coordinate: %s', str(coordinates))
    raise NameError('Malformed coordinate!')

if __name__ == '__main__':
    formatter = logging.Formatter("[%(asctime)s] %(levelname)-7s (%(filename)s:%(lineno)3s) %(message)s", "%Y-%m-%d %H:%M:%S")
    handler_stream = logging.StreamHandler()
    handler_stream.setFormatter(formatter)
    handler_stream.setLevel(logging.DEBUG)
    log = logging.getLogger('abb')
    log.setLevel(logging.DEBUG)
    log.addHandler(handler_stream)
    
