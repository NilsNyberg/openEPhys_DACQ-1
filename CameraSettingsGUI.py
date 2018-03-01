### This program handles the calibration and settings for Raspberry Pi Cameras
### that are used for tracking LED(s) during electrophysiological recordings.

### By Sander Tanni, May 2017, UCL

# How to add more cameras (RPis):
# Add more Cameras to the Individual Cameras list with QDesigner
# Add plots for new cameras to the f_plots with QDesigner
# Follow the objectName convention of previous items
# Add new objectNames to the lists in CameraSettings.__init__ GUI variables lines

# How to add more general camera settings:
# Add new edited copies of the frames to the General Settings list with QDesigner
# Include the new input fields in self.get_RPiSettings(self) and self.load(self)

from PyQt4 import QtGui
import CameraSettingsGUIDesign
import sys
import os
from sshScripts import ssh
import cPickle as pickle
import pyqtgraph as pg
import numpy as np
from shutil import copyfile, rmtree
from PIL import Image
from HelperFunctions import openSingleFileDialog
from tempfile import mkdtemp
from RecordingManager import update_tracking_camera_files
import threading
from copy import deepcopy

def show_message(message, message_more=None):
    # This function is used to display a message in a separate window
    msg = QtGui.QMessageBox()
    msg.setIcon(QtGui.QMessageBox.Information)
    msg.setText(message)
    if message_more:
        msg.setInformativeText(message_more)
    msg.setWindowTitle('Message')
    msg.setStandardButtons(QtGui.QMessageBox.Ok)
    msg.exec_()

def plotImage(im_view, image):
    # This function is used to display an image in any of the plots in the bottom
    # Add white padding to frame the image
    image = np.pad(image, [(1, 1), (1, 1), (0, 0)], mode='constant', constant_values=255)
    im_view.clear()
    view = im_view.addViewBox()
    view.setAspectLocked(True)
    im_item = pg.ImageItem()
    view.addItem(im_item)
    im_item.setImage(np.swapaxes(np.flipud(image),0,1))

def get_current_image(RPiSettings, n_rpi, RPiImageTempFolder):
    # Use SSH connection to send commands
    connection = ssh(RPiSettings['RPiIP'][n_rpi], RPiSettings['username'], RPiSettings['password'])
    # Run getImage.py on RPi to capture a frame
    com_str = 'cd ' + RPiSettings['tracking_folder'] + ' && python getImage.py'
    connection.sendCommand(com_str)
    connection.disconnect()
    # Copy over output files to local TEMP folder
    src_file = RPiSettings['username'] + '@' + RPiSettings['RPiIP'][n_rpi] + ':' + \
               RPiSettings['tracking_folder'] + '/frame.jpg'
    dst_file = os.path.join(RPiImageTempFolder, 'frame' + str(n_rpi) + '.jpg')
    callstr = 'scp -q ' + src_file + ' ' + dst_file
    _ = os.system(callstr)

def calibrate_camera(RPiSettings, n_rpi, RPiCalibrationTempFolder):
    # Use SSH connection to send commands
    connection = ssh(RPiSettings['RPiIP'][n_rpi], RPiSettings['username'], RPiSettings['password'])
    # Run calibrate.py on RPi
    com_str = 'cd ' + RPiSettings['tracking_folder'] + ' && python calibrate.py'
    connection.sendCommand(com_str)
    connection.disconnect()
    # Copy over output files to local TEMP folder
    src_file = RPiSettings['username'] + '@' + RPiSettings['RPiIP'][n_rpi] + ':' + \
               RPiSettings['tracking_folder'] + '/calibrationData.p'
    dst_file = os.path.join(RPiCalibrationTempFolder, 'calibrationData' + str(n_rpi) + '.p')
    callstr = 'scp -q ' + src_file + ' ' + dst_file
    _ = os.system(callstr)

def get_overlay_on_current_image(RPiSettings, n_rpi, RPiImageTempFolder):
    # Use SSH connection to send commands
    connection = ssh(RPiSettings['RPiIP'][n_rpi], RPiSettings['username'], RPiSettings['password'])
    # Run getImage.py on RPi to capture a frame
    com_str = 'cd ' + RPiSettings['tracking_folder'] + ' && python calibrate.py overlay'
    connection.sendCommand(com_str)
    connection.disconnect()
    # Copy over output files to local TEMP folder
    src_file = RPiSettings['username'] + '@' + RPiSettings['RPiIP'][n_rpi] + ':' + \
               RPiSettings['tracking_folder'] + '/overlay.jpg'
    dst_file = os.path.join(RPiImageTempFolder, 'overlay' + str(n_rpi) + '.jpg')
    callstr = 'scp -q ' + src_file + ' ' + dst_file
    _ = os.system(callstr)


class CameraSettings(QtGui.QMainWindow, CameraSettingsGUIDesign.Ui_MainWindow):
    def __init__(self, parent=None):
        super(CameraSettings, self).__init__(parent=parent)
        self.setupUi(self)
        self.parent = parent
        # Set up GUI variables
        self.trackingFolder = '/home/pi/Tracking'
        self.pt_rpi_ips = [self.pt_rpi_ip_1, self.pt_rpi_ip_2, self.pt_rpi_ip_3, self.pt_rpi_ip_4]
        self.cb_rpis = [self.cb_rpi_1, self.cb_rpi_2, self.cb_rpi_3, self.cb_rpi_4]
        self.pt_rpi_loc = [self.pt_rpi_loc_1, self.pt_rpi_loc_2, self.pt_rpi_loc_3, self.pt_rpi_loc_4]
        self.im_views = [self.im_view_1, self.im_view_2, self.im_view_3, self.im_view_4]
        self.calibrationData = [None] * len(self.cb_rpis)
        # Set GUI interaction connections
        self.pb_show_image.clicked.connect(lambda:self.show_image())
        self.pb_calibrate.clicked.connect(lambda:self.calibrate())
        self.pb_show_calibration.clicked.connect(lambda:self.show_calibration())
        self.pb_overlay_calibration.clicked.connect(lambda:self.overlay())
        self.pb_test_tracking.clicked.connect(lambda:self.test_tracking())
        self.pb_load.clicked.connect(lambda:self.load())
        self.pb_save.clicked.connect(lambda:self.save())
        self.pb_apply.clicked.connect(lambda:self.apply())
        self.pb_cancel.clicked.connect(lambda:self.cancel())
        # Initialize Exposure Setting list
        itemstrings = ['off', 'auto', 'night', 'nightpreview', 'backlight', 'spotlight', 'sports', \
                       'snow', 'beach', 'verylong', 'fixedfps', 'antishake', 'fireworks']
        self.lw_exposure_settings.addItems(itemstrings)
        self.lw_exposure_settings.setCurrentRow(1)

    def get_RPiSettings(self):
        # Check which LED option is checked
        if self.rb_led_single.isChecked():
            LEDmode = 'single'
        elif self.rb_led_double.isChecked():
            LEDmode = 'double'
        # Check if saving images is requested
        if self.rb_save_im_yes.isChecked():
            save_frames = True
        elif self.rb_save_im_no.isChecked():
            save_frames = False
        # Put resolution into integer format
        tmp = str(self.pt_resolution.toPlainText())
        CamResolution = [int(tmp[:tmp.find(',')]), int(tmp[tmp.find(',') + 1:])]
        # Put camera settings from GUI to a dictionary
        use_RPi_Bool = np.array([0] * len(self.cb_rpis), dtype=bool)
        RPiIP = []
        RPi_Usage = []
        RPi_location = []
        for n_rpi in range(len(self.cb_rpis)):
            RPiIP.append(str(self.pt_rpi_ips[n_rpi].toPlainText()))
            RPi_Usage.append(self.cb_rpis[n_rpi].isChecked())
            use_RPi_Bool[n_rpi] = self.cb_rpis[n_rpi].isChecked()
            RPi_location.append(str(self.pt_rpi_loc[n_rpi].toPlainText()))
        use_RPi_nrs = list(np.arange(len(self.cb_rpis))[use_RPi_Bool])
        RPiSettings = {'LEDmode': LEDmode, 
                       'save_frames': save_frames, 
                       'arena_size': [float(str(self.pt_arena_size_x.toPlainText())), float(str(self.pt_arena_size_y.toPlainText()))], 
                       'calibration_n_dots': [int(str(self.pt_ndots_x.toPlainText())), int(str(self.pt_ndots_y.toPlainText()))], 
                       'corner_offset': [float(str(self.pt_offset_x.toPlainText())), float(str(self.pt_offset_y.toPlainText()))], 
                       'calibration_spacing': float(str(self.pt_calibration_spacing.toPlainText())), 
                       'camera_iso': int(str(self.pt_camera_iso.toPlainText())), 
                       'LED_separation': float(str(self.pt_LED_separation.toPlainText())), 
                       'LED_angle': float(str(self.pt_LED_angle.toPlainText())), 
                       'camera_transfer_radius': float(str(self.pt_camera_transfer_radius.toPlainText())), 
                       'shutter_speed': int(str(self.pt_shutter_speed.toPlainText())), 
                       'exposure_setting': str(self.lw_exposure_settings.currentItem().text()), 
                       'exposure_settings_selection': self.lw_exposure_settings.currentRow(), 
                       'smoothing_radius': int(str(self.pt_smooth_r.toPlainText())), 
                       'resolution': CamResolution, 
                       'centralIP': str(self.pt_local_ip.toPlainText()), 
                       'password': str(self.pt_rpi_password.toPlainText()), 
                       'username': str(self.pt_rpi_username.toPlainText()), 
                       'pos_port': str(self.pt_posport.toPlainText()), 
                       'stop_port': str(self.pt_stopport.toPlainText()), 
                       'RPiIP': RPiIP, 
                       'RPi_Usage': RPi_Usage, 
                       'use_RPi_nrs': use_RPi_nrs, 
                       'RPi_location': RPi_location, 
                       'tracking_folder': self.trackingFolder, 
                       'calibrationData': self.calibrationData}

        return RPiSettings

    def load(self,RPiSettings=None):
        if RPiSettings is None:
            # Load RPiSettings
            loadFile = openSingleFileDialog('load', suffix='p', caption='Select settings file to load')
            with open(loadFile,'rb') as file:
                settings = pickle.load(file)
                RPiSettings = settings['RPiSettings']
        # Set current calibration data
        self.calibrationData = RPiSettings['calibrationData']
        # Put RPiSettings to GUI
        if RPiSettings['LEDmode'] == 'single':
            self.rb_led_single.setChecked(True)
        elif RPiSettings['LEDmode'] == 'double':
            self.rb_led_double.setChecked(True)
        if RPiSettings['save_frames']:
            self.rb_save_im_yes.setChecked(True)
        elif not RPiSettings['save_frames']:
            self.rb_save_im_no.setChecked(True)
        self.pt_arena_size_x.setPlainText(str(RPiSettings['arena_size'][0]))
        self.pt_arena_size_y.setPlainText(str(RPiSettings['arena_size'][1]))
        self.pt_ndots_x.setPlainText(str(RPiSettings['calibration_n_dots'][0]))
        self.pt_ndots_y.setPlainText(str(RPiSettings['calibration_n_dots'][1]))
        self.pt_offset_x.setPlainText(str(RPiSettings['corner_offset'][0]))
        self.pt_offset_y.setPlainText(str(RPiSettings['corner_offset'][1]))
        self.pt_calibration_spacing.setPlainText(str(RPiSettings['calibration_spacing']))
        self.pt_smooth_r.setPlainText(str(RPiSettings['smoothing_radius']))
        self.pt_LED_separation.setPlainText(str(RPiSettings['LED_separation']))
        self.pt_LED_angle.setPlainText(str(RPiSettings['LED_angle']))
        self.pt_camera_transfer_radius.setPlainText(str(RPiSettings['camera_transfer_radius']))
        self.pt_camera_iso.setPlainText(str(RPiSettings['camera_iso']))
        self.pt_shutter_speed.setPlainText(str(RPiSettings['shutter_speed']))
        self.lw_exposure_settings.setCurrentRow(RPiSettings['exposure_settings_selection'])
        CamRes = RPiSettings['resolution']
        CamResStr = str(CamRes[0]) + ', ' + str(CamRes[1])
        self.pt_resolution.setPlainText(CamResStr)
        self.pt_local_ip.setPlainText(RPiSettings['centralIP'])
        self.pt_rpi_password.setPlainText(RPiSettings['password'])
        self.pt_rpi_username.setPlainText(RPiSettings['username'])
        self.pt_posport.setPlainText(RPiSettings['pos_port'])
        self.pt_stopport.setPlainText(RPiSettings['stop_port'])
        for n_rpi in range(len(RPiSettings['RPiIP'])):
            self.pt_rpi_ips[n_rpi].setPlainText(RPiSettings['RPiIP'][n_rpi])
            self.cb_rpis[n_rpi].setChecked(RPiSettings['RPi_Usage'][n_rpi])
            self.pt_rpi_loc[n_rpi].setPlainText(RPiSettings['RPi_location'][n_rpi])
        self.trackingFolder = RPiSettings['tracking_folder']

    def save(self):
        RPiSettings = self.get_RPiSettings()
        # Get folder to which data will be saved
        path = openSingleFileDialog('save', suffix='p', caption='Save file name and location')
        # Save data
        Settings = {'RPiSettings': RPiSettings}
        with open(path, 'wb') as file:
            pickle.dump(Settings, file)

    def apply(self):
        RPiSettings = self.get_RPiSettings()
        update_tracking_camera_files(RPiSettings)
        self.parent.Settings['RPiSettings'] = deepcopy(RPiSettings)
        self.close()

    def cancel(self):
        self.close()

    def show_image(self):
        RPiSettings = self.get_RPiSettings()
        update_tracking_camera_files(RPiSettings)
        if len(RPiSettings['use_RPi_nrs']) == 0:
            print('No cameras selected')
        else:
            print('Getting images ...')
            # Acquire current image from all tracking RPis
            RPiImageTempFolder = mkdtemp('RPiImageTempFolder')
            T_getRPiImage = []
            for n_rpi in RPiSettings['use_RPi_nrs']:
                T = threading.Thread(target=get_current_image, args=[RPiSettings, n_rpi, RPiImageTempFolder])
                T.start()
                T_getRPiImage.append(T)
            for T in T_getRPiImage:
                T.join()
            # Plot current frame for each RPi
            for n_rpi in RPiSettings['use_RPi_nrs']:
                image = Image.open(os.path.join(RPiImageTempFolder, 'frame' + str(n_rpi) + '.jpg'))
                plotImage(self.im_views[n_rpi], image)
            rmtree(RPiImageTempFolder)
            print('Images displayed.')

    def calibrate(self):
        RPiSettings = self.get_RPiSettings()
        update_tracking_camera_files(RPiSettings)
        if len(RPiSettings['use_RPi_nrs']) == 0:
            print('No cameras selected')
        else:
            print('Calibrating cameras ...')
            # Get calibration data from all cameras
            RPiCalibrationTempFolder = mkdtemp('RPiCalibrationTempFolder')
            T_calibrateRPi = []
            for n_rpi in RPiSettings['use_RPi_nrs']:
                T = threading.Thread(target=calibrate_camera, args=[RPiSettings, n_rpi, RPiCalibrationTempFolder])
                T.start()
                T_calibrateRPi.append(T)
            for T in T_calibrateRPi:
                T.join()
            # Load calibration data
            for n_rpi in RPiSettings['use_RPi_nrs']:
                with open(os.path.join(RPiCalibrationTempFolder, 'calibrationData' + str(n_rpi) + '.p'), 'rb') as file:
                    self.calibrationData[n_rpi] = pickle.load(file)
            # Delete temporary folder
            rmtree(RPiCalibrationTempFolder)
            # Show calibration data
            self.show_calibration()

    def show_calibration(self):
        # Loads current calibrationData and shows it in the plots
        RPiSettings = self.get_RPiSettings()
        if len(RPiSettings['use_RPi_nrs']) == 0:
            print('No cameras selected')
        else:
            for n_rpi in RPiSettings['use_RPi_nrs']:
                if not (RPiSettings['calibrationData'][n_rpi] is None):
                    image = RPiSettings['calibrationData'][n_rpi]['image']
                else:
                    image = np.zeros((608,800,3), dtype=np.uint8)
                    image[:,:,0] = 255
                plotImage(self.im_views[n_rpi], image)

    def overlay(self):
        # Captures current image and overlays on it the currently active calibration chessboard corner pattern.
        RPiSettings = self.get_RPiSettings()
        update_tracking_camera_files(RPiSettings)
        if len(RPiSettings['use_RPi_nrs']) == 0:
            print('No cameras selected')
        else:
            print('Getting calibration overlay images ...')
            # Acquire current image from all tracking RPis
            RPiImageTempFolder = mkdtemp('RPiImageTempFolder')
            T_getRPiImage = []
            for n_rpi in RPiSettings['use_RPi_nrs']:
                T = threading.Thread(target=get_overlay_on_current_image, args=[RPiSettings, n_rpi, RPiImageTempFolder])
                T.start()
                T_getRPiImage.append(T)
            for T in T_getRPiImage:
                T.join()
            # Plot current image with overlay for each RPi
            for n_rpi in RPiSettings['use_RPi_nrs']:
                image = Image.open(os.path.join(RPiImageTempFolder, 'overlay' + str(n_rpi) + '.jpg'))
                plotImage(self.im_views[n_rpi], image)
            print('Calibration overlay displayed.')

    def test_tracking(self):
        # Opens up a new window for displaying the primary LED positions as detected
        # and error of each RPi from the mean of RPis
        from PyQt4.QtCore import QTimer
        import RPiInterface as rpiI
        from scipy.spatial.distance import euclidean

        def stop_test_tracking(self):
            # Stops the tracking process and closes the test_tracking window
            self.tracking_timer.stop()
            self.RPIpos.close()
            self.test_tracking_win.close()

        def update_position_text(self):
            # Updates the data in the textboxes
            with self.RPIpos.posDatasLock:
                posDatas = self.RPIpos.posDatas # Retrieve latest position data
            # Get Position values of all RPis and update text boxes
            positions = np.zeros((len(posDatas), 2), dtype=np.float32)
            for nRPi in range(len(posDatas)):
                if posDatas[nRPi]:
                    positions[nRPi, 0] = posDatas[nRPi][3]
                    positions[nRPi, 1] = posDatas[nRPi][4]
                    # Update the text boxes for this RPi
                    self.pt_RPinr[nRPi].setText('%d' % posDatas[nRPi][0])
                    self.pt_posX[nRPi].setText('%.1f' % positions[nRPi, 0])
                    self.pt_posY[nRPi].setText('%.1f' % positions[nRPi, 1])
                else:
                    positions[nRPi, 0] = None
                    positions[nRPi, 1] = None
            # Compute error from mean of all RPis and insert in text box
            if not np.any(np.isnan(positions)):
                for nRPi in range(len(posDatas)):
                    distance = euclidean(np.mean(positions, axis=0), positions[nRPi, :])
                    self.pt_poserror[nRPi].setText('%.1f' % distance)

        # Get RPi Settings
        RPiSettings = self.get_RPiSettings()
        # Set up dialog box
        self.test_tracking_win = QtGui.QDialog()
        self.test_tracking_win.setWindowTitle('Test Tracking')
        vbox = QtGui.QVBoxLayout()
        # Add box titles for columns
        hbox_titles = QtGui.QHBoxLayout()
        pt_test_tracking_1 = QtGui.QLineEdit('RPi nr')
        pt_test_tracking_1.setReadOnly(True)
        hbox_titles.addWidget(pt_test_tracking_1)
        pt_test_tracking_2 = QtGui.QLineEdit('pos X')
        pt_test_tracking_2.setReadOnly(True)
        hbox_titles.addWidget(pt_test_tracking_2)
        pt_test_tracking_3 = QtGui.QLineEdit('pox Y')
        pt_test_tracking_3.setReadOnly(True)
        hbox_titles.addWidget(pt_test_tracking_3)
        pt_test_tracking_4 = QtGui.QLineEdit('error')
        pt_test_tracking_4.setReadOnly(True)
        hbox_titles.addWidget(pt_test_tracking_4)
        vbox.addLayout(hbox_titles)
        # Add rows for all RPis
        self.pt_RPinr = []
        self.pt_posX = []
        self.pt_posY = []
        self.pt_poserror = []
        hbox_pos = []
        for nRPi in range(len(RPiSettings['use_RPi_nrs'])):
            hbox_pos.append(QtGui.QHBoxLayout())
            # Add RPi nr box
            self.pt_RPinr.append(QtGui.QLineEdit())
            self.pt_RPinr[nRPi].setReadOnly(True)
            hbox_pos[nRPi].addWidget(self.pt_RPinr[nRPi])
            # Add pos X box
            self.pt_posX.append(QtGui.QLineEdit())
            self.pt_posX[nRPi].setReadOnly(True)
            hbox_pos[nRPi].addWidget(self.pt_posX[nRPi])
            # Add pos Y box
            self.pt_posY.append(QtGui.QLineEdit())
            self.pt_posY[nRPi].setReadOnly(True)
            hbox_pos[nRPi].addWidget(self.pt_posY[nRPi])
            # Add error box
            self.pt_poserror.append(QtGui.QLineEdit())
            self.pt_poserror[nRPi].setReadOnly(True)
            hbox_pos[nRPi].addWidget(self.pt_poserror[nRPi])
            vbox.addLayout(hbox_pos[nRPi])
        # Add stop button
        self.pb_stop_tracking = QtGui.QPushButton('Stop Test')
        self.pb_stop_tracking.clicked.connect(lambda:stop_test_tracking(self))
        vbox.addWidget(self.pb_stop_tracking)
        # Finalise dialog box parameters
        self.test_tracking_win.setLayout(vbox)
        self.test_tracking_win.setGeometry(300, 200, 250, 20 * (len(RPiSettings['use_RPi_nrs']) + 2))
        # Start the RPis
        update_tracking_camera_files(RPiSettings)
        trackingControl = rpiI.TrackingControl(RPiSettings)
        trackingControl.start()
        # Set up RPi latest position updater
        self.RPIpos = rpiI.onlineTrackingData(RPiSettings)
        # Set up constant update of position fields with QTimer
        self.tracking_timer = QTimer()
        self.tracking_timer.timeout.connect(lambda:update_position_text(self))
        self.tracking_timer.start(33)
        # Open up the dialog window
        self.test_tracking_win.exec_()
        # When dialog window closes, stop the RPis
        trackingControl.stop()

# The following is the default ending for a QtGui application script
def main():
    app = QtGui.QApplication(sys.argv)
    form = CameraSettings()
    form.show()
    app.exec_()
    
if __name__ == '__main__':
    main()