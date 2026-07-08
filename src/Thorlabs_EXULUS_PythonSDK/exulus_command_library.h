#pragma once

#ifdef EXULUS_COMMAND_LIBRARY_EXPORTS
#define EXULUS_COMMAND_LIBRARY_API extern "C" __declspec(dllexport)
#else
#define EXULUS_COMMAND_LIBRARY_API extern "C" __declspec(dllimport)
#endif

/// <summary>
/// list all the possible port on this computer.
/// </summary>
/// <param name="serial_no">port list returned string include serial number and device descriptor, separated by comma</param>
/// <returns>non-negative number: number of device in the list; negative number: failed.</returns>
EXULUS_COMMAND_LIBRARY_API int list(char *serial_no,int length);

/// <summary>
///  open port function.
/// </summary>
/// <param name="serial_no">serial number of the device to be opened, use List function to get exist list first.</param>
/// <param name="n_baud">bit per second of port</param>
/// <param name="timeout">set timeout value in (s)</param>
/// <returns> non-negative number: hdl number returned successfully; negative number: failed.</returns>
EXULUS_COMMAND_LIBRARY_API int open(char* serial_no, int n_baud, int timeout);

/// <summary>
/// check opened status of port
/// </summary>
/// <param name="serial_no">serial number of the device to be checked.</param>
/// <returns> 0: port is not opened; 1: port is opened.</returns>
EXULUS_COMMAND_LIBRARY_API int is_open(char* serial_no);

/// <summary>
/// close current opened port
/// </summary>
/// <param name="hdl">handle of port.</param>
/// <returns> 0: success; negative number: failed.</returns>
EXULUS_COMMAND_LIBRARY_API int close(int hdl);

/// <summary>
/// set time out value for read or write process.
/// </summary>
/// <param name="hdl">handle of port.</param>
/// <param name="time">time out value</param>
/// <returns> 0: success; negative number: failed.</returns>
EXULUS_COMMAND_LIBRARY_API int set_timeout(int hdl, int time);


/// <summary>
/// <p>Check if the device communication is ok.</p>
/// </summary>
/// <param name="hdl">handle of port.</param>
/// <param name="ack_code">Acknowledge (0x06), Not Acknowledge (0x09), SPI_Busy (0xBB)</param>
/// <returns>
/// <p>0: success; negative number: failed.</p>
/// <p>0xEB: time out;</p>
/// <p>0xED: invalid string buffer;</p>
/// </returns>
EXULUS_COMMAND_LIBRARY_API int check_communication(int hdl, unsigned char& ack_code);



/// <summary>
/// <p>Get screen Horizontal Flip.</p>
/// </summary>
/// <param name="hdl">handle of port.</param>
/// <param name="flip">
/// <p>Return Flip Status in Horizontal:</p>
/// <p>0x00: Flip in Horizontal Off</p>
/// <p>0x01: Flip in Horizontal On</p>
/// </param>
/// <returns>
/// <p>0: success; negative number: failed.</p>
/// <p>0xEB: time out;</p>
/// <p>0xED: invalid string buffer;</p>
/// </returns>
EXULUS_COMMAND_LIBRARY_API int get_screen_horizontal_flip(int hdl, unsigned char& flip);

/// <summary>
/// <p>Set screen Horizontal Flip.</p>
/// </summary>
/// <param name="hdl">handle of port.</param>
/// <param name="flip">
/// <p>Return Flip Status in Horizontal:</p>
/// <p>0x00: Flip in Horizontal Off</p>
/// <p>0x01: Flip in Horizontal On</p>
/// </param>
/// <returns>
/// <p>0: success; negative number: failed.</p>
/// <p>0xEB: time out;</p>
/// <p>0xED: invalid string buffer;</p>
/// </returns>
EXULUS_COMMAND_LIBRARY_API int set_screen_horizontal_flip(int hdl, unsigned char flip);

/// <summary>
/// <p>Get Image Vertical Flip.</p>
/// </summary>
/// <param name="hdl">handle of port.</param>
/// <param name="flip">
/// <p>Return Flip Status in Vertical:</p>
/// <p>0x00: Flip in Vertical Off</p>
/// <p>0x01: Flip in Vertical On</p>
/// </param>
/// <returns>
/// <p>0: success; negative number: failed.</p>
/// <p>0xEB: time out;</p>
/// <p>0xED: invalid string buffer;</p>
/// </returns>
EXULUS_COMMAND_LIBRARY_API int get_screen_vertical_flip(int hdl, unsigned char& flip);

/// <summary>
/// <p>Set Image Vertical Flip.</p>
/// </summary>
/// <param name="hdl">handle of port.</param>
/// <param name="flip">
/// <p>Return Flip Status in Vertical:</p>
/// <p>0x00: Flip in Vertical Off</p>
/// <p>0x01: Flip in Vertical On</p>
/// </param>
/// <returns>
/// <p>0: success; negative number: failed.</p>
/// <p>0xEB: time out;</p>
/// <p>0xED: invalid string buffer;</p>
/// </returns>
EXULUS_COMMAND_LIBRARY_API int set_screen_vertical_flip(int hdl, unsigned char flip);


/// <summary>
/// <p>Get Gamma Table Location.</p>
/// </summary>
/// <param name="hdl">handle of port.</param>
/// <param name="location">
/// <p>Return Gamma Table Location:</p>
/// <p>0x00: #1 Gamma Table</p>
/// <p>0x01: #2 Gamma Table</p>
/// </param>
/// <returns>
/// <p>0: success; negative number: failed.</p>
/// <p>0xEB: time out;</p>
/// <p>0xED: invalid string buffer;</p>
/// </returns>
EXULUS_COMMAND_LIBRARY_API int get_phase_stroke_mode(int hdl, unsigned char& location);

/// <summary>
/// <p>Set Gamma Table Location.</p>
/// </summary>
/// <param name="hdl">handle of port.</param>
/// <param name="location">
/// <p>Return Gamma Table Location:</p>
/// <p>0x00: #1 Gamma Table/Full Wave</p>
/// <p>0x01: #2 Gamma Table/Half Wave</p>
/// </param>
/// <returns>
/// <p>0: success; negative number: failed.</p>
/// <p>0xEB: time out;</p>
/// <p>0xED: invalid string buffer;</p>
/// </returns>
EXULUS_COMMAND_LIBRARY_API int set_phase_stroke_mode(int hdl, unsigned char location);

/// <summary>
/// <p>Get Internal Pattern Generator Status.</p>
/// </summary>
/// <param name="hdl">handle of port.</param>
/// <param name="status">
/// <p>Return Internal Pattern Generator Status:</p>
/// <p>0x00: Internal Pattern Generator Off</p>
/// <p>0x01: Internal Pattern Generator On</p>
/// </param>
/// <returns>
/// <p>0: success; negative number: failed.</p>
/// <p>0xEB: time out;</p>
/// <p>0xED: invalid string buffer;</p>
/// </returns>
EXULUS_COMMAND_LIBRARY_API int get_test_pattern_status(int hdl, unsigned char& status);

/// <summary>
/// <p>Set Internal Pattern Generator Status.</p>
/// </summary>
/// <param name="hdl">handle of port.</param>
/// <param name="status">
/// <p>Return Internal Pattern Generator Status:</p>
/// <p>0x00: Internal Pattern Generator Off</p>
/// <p>0x01: Internal Pattern Generator On</p>
/// </param>
/// <returns>
/// <p>0: success; negative number: failed.</p>
/// <p>0xEB: time out;</p>
/// <p>0xED: invalid string buffer;</p>
/// </returns>
EXULUS_COMMAND_LIBRARY_API int set_test_pattern_status(int hdl, unsigned char status);


/// <summary>
/// <p>Set Internal Pattern.</p>
/// </summary>
/// <param name="hdl">handle of port.</param>
/// <returns>
/// <p>0: success; negative number: failed.</p>
/// <p>0xEB: time out;</p>
/// <p>0xED: invalid string buffer;</p>
/// </returns>
EXULUS_COMMAND_LIBRARY_API int save_default_setting(int hdl);

