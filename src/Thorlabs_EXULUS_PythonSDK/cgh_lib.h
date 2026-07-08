#ifndef CGH_LIB_HEADER
#define CGH_LIB_HEADER
#ifdef CGH_LIB_EXPORTS
#define CGH_LIB_API extern "C" __declspec(dllexport)
#else
#define CGH_LIB_API extern "C" __declspec(dllimport)
#endif

enum result{
	SUCCESS = 1,
	INIT_PIX_SIZE_ERROR = -1,
	CROSS_SHIFT_SIZE_ERROR = -2,
	CROSS_SHIFT_BUFFER_ERROR = -3,
	RAND_PHASE_FFT_BUFFER_ERROR = -4,
	CGH_LIB_INIT_ERROR = -5,
	CORE_CREATE_HDL_ERROR = -6,
	IMG_RESIZE_BUFFER_ERROR = -7,
	INDEX_IS_OUTOF_RANGE = -8,
	INVALID_INPUT_ERROR = -9,
	INTERNAL_ERROR = -0xEA,
};

enum resize_mode{
	CENTER = 0,   // center mode
    FIT = 1,      // fit mode  
	FILL = 2,     // fill mode
	STRETCH = 3   // stretch mode
};

/// <summary>
///  initilize cgh library.
/// </summary>
/// <returns> SUCCESS: success; CGH_LIB_INIT_ERROR: initilize lib failed;</returns>
CGH_LIB_API int cgh_lib_init();

/// <summary>
///  create cgh core before calculate.
/// </summary>
/// <returns>non-negative number: hdl number returned successfully; negative number : failed.</returns>
CGH_LIB_API int cgh_core_create();

/// <summary>
///  close the created cgh core by hdl
/// </summary>
/// <param name="hdl">handle of core.</param>
/// <returns> SUCCESS: success; other number : failed.</returns>
CGH_LIB_API int cgh_core_close(int hdl);

/// <summary>
///  calculate the cgh image
/// </summary>
/// <param name="hdl">handle of core.</param>
/// <param name="buffer">input image buffer, the result buffer with same pointer.</param>
/// <param name="stroke_m">it's according to the wavelength.</param>
/// <returns> SUCCESS: success; other number : failed.</returns>
CGH_LIB_API int cgh_core_calc(int hdl, unsigned char * buffer, float stroke_m);

/// <summary>
///  set all parametes for cgh core
/// </summary>
/// <param name="hdl">handle of core.</param>
/// <param name="w_pixel">horizontal pixel number of LCD panel.</param>
/// <param name="h_pixel">vertical pixel number of LCD panel.</param>
/// <param name="pix_size_m">physical pixel size of LCD panel, unit meter.</param>
/// <param name="distance">focus distance, unit meter.</param>
/// <param name="wavelenth">wavelength of light, unit meter.</param>
/// <returns> SUCCESS: success; other number : failed.</returns>
CGH_LIB_API int cgh_core_update_all(int hdl, int w_pixel, int h_pixel, float pix_size_m, float distance, float wavelenth);

/// <summary>
///  set distance for cgh core
/// </summary>
/// <param name="hdl">handle of core.</param>
/// <param name="distance">focus distance, unit meter.</param>
/// <returns> SUCCESS: success; other number : failed.</returns>
CGH_LIB_API int cgh_core_update_distance(int hdl, float distance);

/// <summary>
///   resize image
/// </summary>
/// <param name="src_buf">piont of source 8 byte image buffer.</param>
/// <param name="src_width">width of source image.</param>
/// <param name="src_height">height of source image.</param>
/// <param name="dst_buf">piont of destination 8 byte image buffer.</param>
/// <param name="dst_width">width of destination image.</param>
/// <param name="dst_height">height of destination image.</param>
/// <param name="mode">resize mode.</param>
/// <param name="background_color">set backgroud color for center/fill mode.</param>
/// <returns> SUCCESS: success; other number: failed.</returns>
CGH_LIB_API int cgh_image_resize(unsigned char *src_buf, int src_width, int src_height,
	unsigned char *dst_buf, int dst_width, int dst_height, int mode, unsigned char background_color = 0);

/// <summary>
///  calculate the cgh image, intergral all paramters, not thread safe
/// </summary>
/// <param name="w_pixel">horizontal pixel number of LCD panel.</param>
/// <param name="h_pixel">vertical pixel number of LCD panel.</param>
/// <param name="pix_size_m">physical pixel size of LCD panel, unit meter.</param>
/// <param name="distance">focus distance, unit meter.</param>
/// <param name="wavelenth">wavelength of light, unit meter.</param>
/// <param name="buffer">input image buffer, the result buffer with same pointer.</param>
/// <param name="stroke_m">it's according to the wavelength.</param>
/// <returns> SUCCESS: success; other number : failed.</returns>
CGH_LIB_API int cgh_core_calc_ext(int w_pixel, int h_pixel, float pix_size_m, float distance, float wavelenth, unsigned char * buffer, float stroke_m);

#endif




