import math
import os
import pathlib
import sys
import tarfile
import tempfile

import numpy as np  # type: ignore[import]
from scipy.interpolate import griddata  # type: ignore[import]
from appdirs import user_data_dir  # type: ignore[import]
import wget  # type: ignore[import]

DATADIR = pathlib.Path(user_data_dir()) / 'tpxo'
DATADIR.mkdir(exist_ok=True, parents=True)


def polar(z):
    a = z.real
    b = z.imag
    r = math.hypot(a, b)
    theta = math.atan2(b, a)
    return r, np.rad2deg(theta)


class TPXO:
    """
    Egbert, Gary D., and Svetlana Y. Erofeeva. "Efficient inverse modeling
        of barotropic ocean tides." Journal of Atmospheric and Oceanic
        Technology 19.2 (2002): 183-204
    """

    def __init__(self):

        _tarfile = os.getenv('TPXO_NETCDF_TARFILE')
        if _tarfile is not None:
            _tarfile = pathlib.Path(_tarfile)
        else:
            _tarfile = DATADIR / 'tpxo9.tar.gz'

        if not _tarfile.is_file():
            fetch_tpxo_file()

        self._tarfile = _tarfile

        self._gfile = pathlib.Path(self._tmpdir.name) / 'DATA/grid_tpxo9'

        self._hfile = pathlib.Path(self._tmpdir.name) / 'DATA/h_tpxo9.v1'

        self._ufile = pathlib.Path(self._tmpdir.name) / 'DATA/u_tpxo9.v1'

        self.x, self.y, _, mask = read_tide_grid(self._gfile)[:4]
        self.mask = ~mask.astype(bool)

    def get_elevation(self, constituent, vertices):
        index = self.constituents.index(constituent.lower().capitalize())
        array = read_elevation_file(self._hfile, index)
        xq = np.asarray([x + 360. for x in vertices[:, 0] if x < 0]).flatten()
        yq = vertices[:, 1].flatten()
        xi, yi = np.meshgrid(self.x, self.y)
        dx = np.mean(np.diff(self.x))
        dy = np.mean(np.diff(self.y))
        xi = xi.flatten()
        yi = yi.flatten()
        idxq = np.where(
                np.logical_and(  # buffer the bbox by 2 difference units
                    np.logical_and(xi >= np.min(xq) - 2 * dx,
                                   xi <= np.max(xq) + 2 * dx),
                    np.logical_and(yi >= np.min(yq) - 2 * dy,
                                   yi <= np.max(yq) + 2 * dy)
                    )
                )
        values = np.ma.zeros((len(vertices),), dtype=array.dtype)
        values.data.real = griddata((xi[idxq], yi[idxq]),
                                    array.real.flatten()[idxq],
                                    (xq, yq), method='nearest')
        values.data.imag = griddata((xi[idxq], yi[idxq]),
                                    array.imag.flatten()[idxq],
                                    (xq, yq), method='nearest')
        amp, phase = [list(data) for data in zip(*map(polar, values))]
        phase = np.abs(np.array(phase)-360)
        idx = np.where(phase >= 360)
        phase[idx] = phase[idx] % 360
        return amp, phase

    def get_velocity(self, constituent, vertices):
        index = self.constituents.index(constituent.lower().capitalize())
        u, v = read_transport_file(self._ufile, index)
        xq = np.asarray([x + 360. for x in vertices[:, 0] if x < 0]).flatten()
        yq = vertices[:, 1].flatten()
        xi, yi = np.meshgrid(self.x, self.y)
        dx = np.mean(np.diff(self.x))
        dy = np.mean(np.diff(self.y))
        xi = xi.flatten()
        yi = yi.flatten()
        idxq = np.where(
                np.logical_and(  # buffer the bbox by 2 difference units
                    np.logical_and(xi >= np.min(xq) - 2 * dx,
                                   xi <= np.max(xq) + 2 * dx),
                    np.logical_and(yi >= np.min(yq) - 2 * dy,
                                   yi <= np.max(yq) + 2 * dy)
                    )
                )
        uval = np.ma.zeros((len(vertices),), dtype=u.dtype)
        vval = np.ma.zeros((len(vertices),), dtype=v.dtype)

        uval.data.real = griddata((xi[idxq], yi[idxq]),
                                  u.real.flatten()[idxq],
                                  (xq, yq), method='nearest')
        uval.data.imag = griddata((xi[idxq], yi[idxq]),
                                  u.imag.flatten()[idxq],
                                  (xq, yq), method='nearest')
        vval.data.real = griddata((xi[idxq], yi[idxq]),
                                  v.real.flatten()[idxq],
                                  (xq, yq), method='nearest')
        vval.data.imag = griddata((xi[idxq], yi[idxq]),
                                  v.imag.flatten()[idxq],
                                  (xq, yq), method='nearest')

        uamp, uphase = [list(data) for data in zip(*map(polar, uval))]
        uphase = np.abs(np.array(uphase)-360)
        uidx = np.where(uphase >= 360)
        uphase[uidx] = uphase[uidx] % 360

        vamp, vphase = [list(data) for data in zip(*map(polar, vval))]
        vphase = np.abs(np.array(vphase)-360)
        vidx = np.where(vphase >= 360)
        vphase[vidx] = vphase[vidx] % 360
        return uamp, uphase, vamp, vphase

    @property
    def constituents(self):
        return [c.capitalize() for c in read_constituents(self._hfile)[0]]

    @property
    def _tarfile(self):
        return self.__tarfile

    @_tarfile.setter
    def _tarfile(self, file: pathlib.Path):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmpdir = pathlib.Path(self._tmpdir.name)
        with tarfile.open(file) as f:
            f.extractall(path=tmpdir)
        self.__tarfile = file


def fetch_tpxo_file():
    url = "https://www.dropbox.com/s/tnxflm8xgpiujwb/tpxo9.tar.gz?dl=1"

    def query_yes_no(question: str, default: str = "yes") -> bool:
        """
        Ask a yes/no question via raw_input() and return their answer.

        :param question: string presented to the user
        :param default: presumed answer if the user just hits <Enter>; must be "yes" (the default), "no", or None (meaning an answer is required of the user) # noqa: E501
        :returns: whether 'yes' or 'no' was selected by the user
        """

        valid = {
            "yes": True,
            "y": True,
            "ye": True,
            "no": False,
            "n": False
        }
        if default is None:
            prompt = " [y/n] "
        elif default == "yes":
            prompt = " [Y/n] "
        elif default == "no":
            prompt = " [y/N] "
        else:
            raise ValueError("invalid default answer: '%s'" % default)

        while 1:
            sys.stdout.write(question + prompt)
            choice = input().lower()
            if default is not None and choice == '':
                return valid[default]
            elif choice in valid.keys():
                return valid[choice]
            else:
                sys.stdout.write(
                    "Please respond with 'yes' or 'no' (or 'y' or 'n').\n")
    q = "******* PLEASE READ *******\n" \
        "A function that is being invoked requires the use of the TPXO" \
        " file which is copyrighted by the " \
        "State of Oregon acting by and through the State Board of Higher " \
        "Education on behalf of Oregon State University.\n" \
        "This data is licensed for non-commercial use.\n" \
        'This software can automatically fetch the TPXO file for you ' \
        'using your internet connection.\n' \
        "By downloading this file and using this software, you are " \
        "accepting the licensing agreement for the TPXO file found here" \
        ":\nhttps://drive.google.com/file/d/1f00WojHqu7_VE5Hg9OdiVBjymH" \
        "76dFCy/view\n" \
        "Do you accept the license terms exposed in the link above and " \
        "approve that this software downloads and install the TPXO file " \
        "using the internet?\n"
    a = query_yes_no(q)
    if a is False:
        raise RuntimeError('No TPXO database found.')
    else:
        print(f'Downloading TPXO database to {str(DATADIR.resolve())}/'
              'tpxo9.tar.gz, please wait... \n')
        wget.download(url, out=str(DATADIR / "tpxo9.tar.gz"))


# def get_elevation_amplitude(constituent, vertices):
    # """
    # tpxo_index_key is either 'ha' or 'hp' based on the keys used internally
    # on the TPXO netcdf file.
    # """        
    # constituent = self.tpxo_constituents.index(constituent)
    # array = tpxo_array[constituent, :, :].flatten()
    # _x = np.asarray([x + 360. for x in vertices[:, 0] if x < 0]).flatten()
    # _y = vertices[:, 1].flatten()
    # x, y = np.meshgrid(self.x, self.y, indexing='ij')
    # x = x.flatten()
    # y = y.flatten()
    # dx = np.mean(np.diff(self.x))
    # dy = np.mean(np.diff(self.y))
    # _idx = np.where(
        # np.logical_and(  # buffer the bbox by 2 difference units
            # np.logical_and(x >= np.min(_x) - 2 * dx,
                           # x <= np.max(_x) + 2 * dx),
            # np.logical_and(y >= np.min(_y) - 2 * dy,
                           # y <= np.max(_y) + 2 * dy)))
    # return griddata(
        # (x[_idx], y[_idx]), array[_idx], (_x, _y), method='nearest')


def install():
    prefix = "/".join(sys.executable.split('/')[:-2])
    file = pathlib.Path(prefix) / 'lib/h_tpxo9.v1.nc'
    TPXO._fetch_tpxo_file(prefix, file)


# https://github.com/tsutterley/pyTMD/blob/47ff266e83b92f0ed75f2710fdedde3f9510bb84/pyTMD/read_tide_model.py#L561-L582
def read_constituents(input_file):
    """
    Read the list of constituents from an elevation or transport file
    Arguments
    ---------
    input_file: input tidal file
    Returns
    -------
    constituents: list of tidal constituent IDs
    nc: number of constituents
    """
    #-- open the file
    fid = open(os.path.expanduser(input_file),'rb')
    ll, = np.fromfile(fid, dtype=np.dtype('>i4'), count=1)
    nx,ny,nc = np.fromfile(fid, dtype=np.dtype('>i4'), count=3)
    fid.seek(16,1)
    constituents = [c.decode("utf-8").rstrip() for c in fid.read(nc*4).split()]
    fid.close()
    return (constituents,nc)


# https://github.com/tsutterley/pyTMD/blob/47ff266e83b92f0ed75f2710fdedde3f9510bb84/pyTMD/read_tide_model.py#L586-L619
def read_elevation_file(input_file,ic):

    """
    Read elevation file to extract real and imaginary components for constituent
    Arguments
    ---------
    input_file: input elevation file
    ic: index of consituent
    Returns
    -------
    h: tidal elevation
    """
    #-- open the file
    fid = open(os.path.expanduser(input_file),'rb')
    ll, = np.fromfile(fid, dtype=np.dtype('>i4'), count=1)
    nx,ny,nc = np.fromfile(fid, dtype=np.dtype('>i4'), count=3)
    #-- extract x and y limits
    ylim = np.fromfile(fid, dtype=np.dtype('>f4'), count=2)
    xlim = np.fromfile(fid, dtype=np.dtype('>f4'), count=2)
    #-- skip records to constituent
    nskip = ic*(nx*ny*8+8) + 8 + ll - 28
    fid.seek(nskip,1)
    #-- real and imaginary components of elevation
    h = np.ma.zeros((ny,nx),dtype=np.complex64)
    h.mask = np.zeros((ny,nx),dtype=np.bool)
    for i in range(ny):
        temp = np.fromfile(fid, dtype=np.dtype('>f4'), count=2*nx)
        h.data.real[i,:] = temp[0:2*nx-1:2]
        h.data.imag[i,:] = temp[1:2*nx:2]
    #-- close the file
    fid.close()
    #-- return the elevation
    return h


# https://github.com/tsutterley/pyTMD/blob/47ff266e83b92f0ed75f2710fdedde3f9510bb84/pyTMD/read_tide_model.py#L712-L752
def read_transport_file(input_file,ic):
    """
    Read transport file to extract real and imaginary components for constituent
    Arguments
    ---------
    input_file: input transport file
    ic: index of consituent
    Returns
    -------
    u: zonal tidal transport
    v: meridional zonal transport
    """
    #-- open the file
    fid = open(os.path.expanduser(input_file),'rb')
    ll, = np.fromfile(fid, dtype=np.dtype('>i4'), count=1)
    nx,ny,nc = np.fromfile(fid, dtype=np.dtype('>i4'), count=3)
    #-- extract x and y limits
    ylim = np.fromfile(fid, dtype=np.dtype('>f4'), count=2)
    xlim = np.fromfile(fid, dtype=np.dtype('>f4'), count=2)
    #-- skip records to constituent
    nskip = ic*(nx*ny*16+8) + 8 + ll - 28
    fid.seek(nskip,1)
    #-- real and imaginary components of transport
    u = np.ma.zeros((ny,nx),dtype=np.complex64)
    u.mask = np.zeros((ny,nx),dtype=np.bool)
    v = np.ma.zeros((ny,nx),dtype=np.complex64)
    v.mask = np.zeros((ny,nx),dtype=np.bool)
    for i in range(ny):
        temp = np.fromfile(fid, dtype=np.dtype('>f4'), count=4*nx)
        u.data.real[i,:] = temp[0:4*nx-3:4]
        u.data.imag[i,:] = temp[1:4*nx-2:4]
        v.data.real[i,:] = temp[2:4*nx-1:4]
        v.data.imag[i,:] = temp[3:4*nx:4]
    #-- close the file
    fid.close()
    #-- return the transport components
    return (u,v)


def read_tide_grid(input_file):
    """
    Read grid file to extract model coordinates, bathymety, masks and indices
    Arguments
    ---------
    input_file: input grid file
    Returns
    -------
    x: x-coordinates of input grid
    y: y-coordinates of input grid
    hz: model bathymety
    mz: land/water mask
    iob: open boundary index
    dt: time step
    """
    #-- open the file
    fid = open(os.path.expanduser(input_file),'rb')
    fid.seek(4,0)
    #-- read data as big endian
    #-- get model dimensions and limits
    nx, = np.fromfile(fid, dtype=np.dtype('>i4'), count=1)
    ny, = np.fromfile(fid, dtype=np.dtype('>i4'), count=1)
    #-- extract x and y limits (these could be latitude and longitude)
    ylim = np.fromfile(fid, dtype=np.dtype('>f4'), count=2)
    xlim = np.fromfile(fid, dtype=np.dtype('>f4'), count=2)
    dt, = np.fromfile(fid, dtype=np.dtype('>f4'), count=1)
    #-- convert longitudinal limits (if x == longitude)
    if (xlim[0] < 0) & (xlim[1] < 0) & (dt > 0):
        xlim += 360.0
    #-- create x and y arrays arrays (these could be lon and lat values)
    dx = (xlim[1] - xlim[0])/nx
    dy = (ylim[1] - ylim[0])/ny
    x = np.linspace(xlim[0]+dx/2.0,xlim[1]-dx/2.0,nx)
    y = np.linspace(ylim[0]+dy/2.0,ylim[1]-dy/2.0,ny)
    #-- read nob and iob from file
    nob, = np.fromfile(fid, dtype=np.dtype('>i4'), count=1)
    if (nob == 0):
        fid.seek(20,1)
        iob = []
    else:
        fid.seek(8,1)
        iob=np.fromfile(fid, dtype=np.dtype('>i4'), count=2*nob).reshape(nob,2)
        fid.seek(8,1)
    #-- read hz matrix
    hz = np.fromfile(fid, dtype=np.dtype('>f4'), count=nx*ny).reshape(ny,nx)
    fid.seek(8,1)
    #-- read mz matrix
    mz = np.fromfile(fid, dtype=np.dtype('>i4'), count=nx*ny).reshape(ny,nx)
    #-- close the file
    fid.close()
    #-- return values
    return (x,y,hz,mz,iob,dt)
