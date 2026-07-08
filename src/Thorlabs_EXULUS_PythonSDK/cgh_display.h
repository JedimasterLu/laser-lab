
#ifndef CGH_DISPLAY_HEADER
#define CGH_DISPLAY_HEADER
#ifdef CGH_LIB_EXPORTS
#define CGH_LIB_API extern "C" __declspec(dllexport)
#else
#define CGH_LIB_API extern "C" __declspec(dllimport)
#endif
/// <summary>
///  get enable monitor count for display
/// </summary>
/// <returns> positive number: count of monitors; nagtive number : failed.</returns>
CGH_LIB_API int cgh_display_get_monitor_count();

/// <summary>
///  create teh display window
/// </summary>
/// <param name="monitor">monitor id, range is from 1 to count</param>
/// <param name="width">width of the window.</param>
/// <param name="width">height of the window.</param>
/// <param name="title">title of the window.</param>
/// <returns>non-negative number: hdl number returned successfully; negative number : failed.</returns>
CGH_LIB_API int cgh_display_create_window(int monitor, int width, int height, char* title);

/// <summary>
///  close the created window by hdl
/// </summary>
/// <param name="window_handle">handle of window.</param>
/// <returns> SUCCESS: success; other number : failed.</returns>
CGH_LIB_API int cgh_display_close_window(int window_handle);

/// <summary>
///  set display window information
/// </summary>
/// <param name="window_handle">handle of window.</param>
/// <param name="window_handle">width of window.</param>
/// <param name="window_handle">height of window.</param>
/// <param name="window_handle">1: gray chanel; 3: RGB channel </param>
/// <returns> SUCCESS: success; other number : failed.</returns>
CGH_LIB_API int cgh_display_set_window_info(int window_handle, int width, int height, char chan_num);

/// <summary>
///  show window
/// </summary>
/// <param name="window_handle">handle of window.</param>
/// <param name="buffer">display image buffer.</param>
/// <returns> SUCCESS: success; other number : failed.</returns>
CGH_LIB_API int cgh_display_show_window(int window_handle, unsigned char * buffer);

#endif
