#!/usr/bin/python

from . import image
import numpy as np
from scipy.optimize import least_squares

def rough_focus(hs, x_initial, y_initial, n_tiles, n_frames, image_name):
    hs.x.move(x_initial)
    hs.y.move(y_initial)
    hs.obj.move(17500)
    # Move to rough focus position
    hs.z.move([21500, 21500, 21500])
    # Take rough focus image
    hs.scan(n_tiles, 1, n_frames, image_name)
    channels = [str(hs.cam1.left_emission),
                str(hs.cam1.right_emission),
                str(hs.cam2.left_emission),
                str(hs.cam2.right_emission)]
    rough_ims = []
    # Stitch rough focus image
    for ch in channels:
        df_x = image.get_image_df(hs.image_path, ch+'_'+image_name)
        rough_ims.append(norm_and_stitch(hs.image_path, df_x, scaled = True))
    scale = rough_ims[0][0][0]
    # Combine channels
    avg_im = image.average_images(rough_ims)
    # Find region of interest
    roi = image.get_roi(avg_im)
    # Find focus points
    focus_points = get_focus_points(roi)
    # Shift focus points towards center
    stage_points = np.zeros(shape=[3,2])
    for i in range(1,4):
        focus_point = image.shift_focus(focus_points[i,:],
                                        focus_points[0,:],
                                        2048/2/scale)
        stage_points[i-1,:]= hs.px_to_step(focus_point, x_initial, y_initial,
                                           scale)

    # Reorder stage points to match z stage motore indice
    ordered_stage_points = np.zeros(shape=[3,2])

    m0 = np.where(stage_points[:,0] == np.min(stage_points[:,0]))[0][0]
    ordered_stage_point[0,:] = stage_points[m0,:]
    stage_points = np.delete(stage_points,m0,0)

    m1 = np.where(stage_points[:,1] == np.min(stage_points[:,1]))[0][0]
    ordered_stage_point[1,:] = stage_points[m1,:]
    stage_points = np.delete(stage_points,m0,0)

    return(ordered_stage_points)

def format_focus(hs, focus1, focus2):
    '''Return valid and normalized focus frame file sizes.

       Parameters:
       - focus1 (array): JPEG file sizes from both channels of camera 1.
       - focus2 (array): JPEG file sizes from both channels of camera 2.

       Returns:
       - array: Valid and normalized focue frame file sizes.

    '''
    # Calculate steps per frame
    # hs.obj.v TODO store velocity in mm/s
    #hs.obj.spum = 262 # steps/um
    # frame_interval = hs.cam1.get_interval() # s/frame TODO

    if len(focus1) != len(focus2):
        print('Number of focus frame mismatch')
    else:
        n_frames = len(focus1)

    if hs.cam1.get_interval() != hs.cam2.get_interval():
        print('Frame interval mismatch')
    else:
        frame_interval = hs.cam1.get_interval()

    spf = hs.obj.vel*1000*hs.obj.spum*frame_interval # steps/frame

    # Remove frames after objective stops moving
    #obj_start = 60292
    #obj_stop = 2621
    _frames = range(n_frames)
    objsteps = hs.obj.focus_start + np.array(_frames)*spf
    objsteps = objsteps[objsteps < hs.obj.focus_stop]

    # Remove first 16 frames
    objsteps = objsteps[16:]

    # Number of formatted frames
    n_f_frames = len(objsteps)

    #formatted focus data
    f_fd = np.empty(shape = (n_f_frames,))

    _size = focus1[16:n_f_frames+16,:] + focus1[16:n_f_frames+16,:]
    _size = _size / np.sum(_size)
    f_fd[:,0] = obj_steps
    f_fd[:,1] = _size

    return f_fd

def gaussian(x, *args):
    """Gaussian function for curve fitting."""

    if len(args) == 1:
      args = args[0]

    n_peaks = int(len(args)/3)


    if len(args) - n_peaks*3 != 0:
      print('Unequal number of parameters')
    else:
      for i in range(n_peaks):
        amp = args[0:n_peaks]
        cen = args[n_peaks:n_peaks*2]
        sigma = args[n_peaks*2:n_peaks*3]

      g_sum = 0
      for i in range(len(amp)):
          g_sum += amp[i]*(1/(sigma[i]*(np.sqrt(2*np.pi))))*(np.exp((-1.0/2.0)*(((x-cen[i])/sigma[i])**2)))

      return g_sum

def res_gaussian(*args):
    """Gaussian residual function for curve fitting."""

    if len(args) == 1:
      args = args[0]

    n_peaks = int(len(args)/3)

    if len(args) - n_peaks*3 != 0:
      print('Unequal number of parameters')
    else:
      for i in range(n_peaks):
        amp = args[0:n_peaks]
        cen = args[n_peaks:n_peaks*2]
        sigma = args[n_peaks*2:n_peaks*3]

      g_sum = 0
      for i in range(len(amp)):
          g_sum += amp[i]*(1/(sigma[i]*np.sqrt(2*np.pi)))*np.exp(-0.5*(((xfun-cen[i])/sigma[i])**2))

      return yfun-g_sum

def fit_mixed_gaussian(hs, data):
    '''Fit focus data & return optimal objective focus step.

       Focus objective step vs frame JPEG file size is fit to a mixed gaussian
       model. The optimal objective focus step is returned at step of the max
       JPEG file size of the fit.

       Parameters:
       - data (array nx2): Focus data where the 1st column are the objetive
                           steps and the 2 column are the valid and normalized
                           focus frame JPEG file size.

       Returns:
       int: The optimal focus objective step. If 1 or -1 is returned, the z
            stage needs to be moved in the +ive or -ive direction to find an
            optimal focus.

    '''

    # initialize values
    max_peaks = 3
    peaks = 1
    # Initialize varibles
    amp = []; amp_lb = []; amp_ub = []
    cen = []; cen_lb = []; cen_ub = []
    sigma = []; sigma_lb = []; sigma_ub = []
    y = data[:,1]
    error = 1
    tolerance = 1e-4
    xfun = data[:,0]; yfun = data[:,1]

    # Add peaks until fit reached threshold
    while peaks <= max_peaks and error > tolerance:
        # set initial guesses
        max_y = np.max(y)
        amp.append(max_y*10000)
        index = np.argmax(y)
        y = np.delete(y, index)
        index = np.where(data[:,1] == max_y)[0][0]
        cen.append(data[index,0])
        sigma.append(np.sum(data[:,1]**2)**0.5*10000)
        p0 = np.array([amp, cen, sigma])
        p0 = p0.flatten()

        # set bounds
        amp_lb.append(0); amp_ub.append(np.inf)
        cen_lb.append(np.min(data[:,0])); cen_ub.append(np.max(data[:,0]))
        sigma_lb.append(0); sigma_ub.append(np.inf)
        lo_bounds = np.array([amp_lb, cen_lb, sigma_lb])
        up_bounds = np.array([amp_ub, cen_ub, sigma_ub])
        lo_bounds = lo_bounds.flatten()
        up_bounds = up_bounds.flatten()

        # Optimize parameters
        results = least_squares(res_gaussian, p0, bounds=(lo_bounds,up_bounds))
        if not results.success:
            print(results.message)
        else:
            error = np.sum(results.fun**2)


        if results.success and error < tolerance:
            _objsteps = range(hs.obj.obj_start, hs.obj.obj_start,
                              int(hs.obj.nyquist_obj/2))
            _focus = gaussian(_objsteps, results.x)
            optobjstep = int(_objsteps[np.argmax(_focus)])]
            return optobjstep
        else:
            if peaks == max_peaks:
                print('No good fit try moving z stage')
                # TODO find direction to move zstage

        return optobjstep

def get_image_df(dir, image_name = None):
  '''Get dataframe of images.

    Parameters:
    dir (path): Directory where images are stored.
    image_name (str): Name common to all images.

    Return
    dataframe: Dataframe of image metadata with image names as index.

  '''

    all_names = os.listdir(dir)
    if image_name is None:
      image_names = all_names
    else:
      image_names = [name for name in all_names if image_name in name]

    # Dataframe for metdata
    metadata = pd.DataFrame(columns = ('channel','flowcell','specimen',
                                       'section','cycle','x','o'))

    # Extract metadata
    for name in image_names:

      meta = name[:-5].split('_')

      # Convert channels to int
      meta[0] = int(meta[0])
      # Remove c from cycle
      meta[4] = int(meta[4][1:])
      # Remove x from xposition
      meta[5] = int(meta[5][1:])
      # Remove o from objective position
      meta[6] = int(meta[6][1:])


      metadata.loc[name] = meta


  metadata.sort_values(by=['flowcell', 'specimen', 'section', 'cycle', 'channel',
                           'o','x'])

  return metadata



def norm_and_stitch(dir, df_x, overlap = 0, scaled = False):
  '''Normalize and stitch scans.

     Images are normalized by matching histogram to first strip in first image.


     Parameters
     dir (path): Directory where image scans are stored.
     df_x (df): Dataframe of metadata of image scans to stitch.
     scaled (bool): True to autoscale images to ~256 Kb, False to not scale.

     Returns
     image: Normalized, stitched, and downscaled image.

  '''

  df_x.sort_values(by=['x'])
  scans = []                                                                    # list of xpos scans
  ref = None
  scale_factor = None
  for name in df_x.index:
    im = io.imread(path.join(dir,name))
    im = im[64:]                                                                # Remove whiteband artifact

    if scaled = True:
        # Scale images so they are ~ 256 kb
        if scale_factor is None:
            size = stat(path.join(dir,name)).st_size
            scale_factor = (2**(log2(size)-18))**0.5
            scale_factor = round(log2(scale_factor))

        im = downscale_local_mean(im, (scale_factor, scale_factor))

    x_px = int(im.shape[1]/8)

    for i in range(8):
      # Stitch images
      sub_im = im[:,(i)*x_px:(i+1)*x_px]

      if ref is None:
        # Make first strip reference for histogram matching
        ref = sub_im
        plane = sub_im
      else:
        sub_im = exposure.match_histograms(sub_im, ref)
        plane = np.append(plane, sub_im, axis = 1)

  plane = plane.astype('uint8')
  plane = img_as_ubyte(plane)

  return plane

ch = '558' , '610'
o = 30117
x = 12344
scale_factor = 16



# Dummy class to hold image data
class image():
  def __init__(self, data):
    self.image = data
    self.elev_map = None
    self.markers = None
    self.segmentation = None
    self.roi = None

# Data frame for images with metadata
df_imgs_ch = pd.DataFrame(columns = ('channel','flowcell','specimen','section',
                                     'cycle','o','image'))

# Stitch all images
# In this dataset there are images from cycle 1 from the 10Ab_mouse_4i experiment
# There are 2 channels, 558 nm (GFAP) and 610 nm (IBA1)
# There are 3 objective positions at 28237, 30117, and 31762
# At each objective position there are 4 scans as x pos = 11714, 12029, 12344, and 12659

for ch in set(metadata.channel):
  #ch = 558
  df_ch = metadata[metadata.channel == ch]
  for o in set(df_ch.o):
    #o = 30117
    df_o = df_ch[df_ch.o == o]
    df_x = df_o.sort_values(by = ['x'])
    meta = [*df_x.iloc[0]]

    title = 'cy'+str(meta[4])+'_ch'+str(ch)+'_o'+str(o)
    meta[5] = meta[6]                                                           # Move objective data
    meta[6] = image(norm_and_stitch(fn, df_x, scale_factor))
    df_imgs_ch.loc[title] = meta

# Show all images
i =0
dim = df_imgs_ch.iloc[0].image.image.shape
n_images = df_imgs_ch.shape[0]
if n_images == 1:
  fig, ax = plt.subplots(figsize=(8, 6))
  for index, row in df_imgs_ch.iterrows():
    ax.imshow(row['image'].image, cmap='Spectral')
    ax.set_title(index)
    ax.axis('off')
elif n_images > 1:
  fig, ax = plt.subplots(1,len(df_imgs_ch), figsize=(dim[0]/10, dim[1]/10*len(df_imgs_ch)))
  for index, row in df_imgs_ch.iterrows():
    ax[i].imshow(row['image'].image,cmap='Spectral')
    ax[i].set_title(index)
    ax[i].axis('off')
    i +=1


    # Make background 0, assume background is most frequent px value
    p_back = stats.mode(im, axis=None)
    imsize = im.shape
    p_back = p_back[0]

    # Make saturated pixels 0
    #p_back, p_sat = np.percentile(im, (10,98))
    p_sat = np.percentile(im, (98,))
    im[im < p_back] = 0
    im[im > p_sat] = 0
