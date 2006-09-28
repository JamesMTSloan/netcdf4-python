import netCDF4_classic
import numpy

__version__ = "0.5"

# Classes Dataset, Dimension and Variable allow handling a multi-file dataset.

class Dataset(netCDF4_classic.Dataset): 

    def __init__(self, cdfFiles):
        """Open a Dataset spanning multiple files,
        making it look as if it was a single file.

        Arguments:
          cdfFiles      sequence of CDF files; the first one will become the
                        "master" file, defining all the record variables which may
                        span subsequent files

        Returns:
          None

        The files are always opened in read-only mode.
                                                        """

        # Open the master file in the base class, so that the CDFMF instance
        # can be used like a CDF instance.
        master = cdfFiles[0]

        # Open the master again, this time as a classic CDF instance. This will avoid
        # calling methods of the CDFMF subclass when querying the master file.
        cdfm = netCDF4_classic.Dataset(master)
        # copy attributes from master.
        for name, value in cdfm.__dict__.items():
            self.__dict__[name] = value

        # Make sure the master defines an unlimited dimension.
        unlimDimId = None
        for dimname,dim in cdfm.dimensions.items():
            if dim.isunlimited():
                unlimDimId = dim
                unlimDimName = dimname
        if unlimDimId is None:
            raise MFDatasetError("master dataset %s does not have an unlimited dimension" % master)

        # Get info on all record variables defined in the master.
        # Make sure the master defines at least one record variable.
        masterRecVar = {}
        for vName,v in cdfm.variables.items():
            dims = v.dimensions
            shape = v.shape
            type = v.dtype
            # Be carefull: we may deal with a scalar (dimensionless) variable.
            # Unlimited dimension always occupies index 0.
            if (len(dims) > 0 and unlimDimName == dims[0]):
                masterRecVar[vName] = (dims, shape, type)
        if len(masterRecVar) == 0:
            raise MFDatasetError("master dataset %s does not have any record variable" % master)

        # Create the following:
        #   cdf       list of Dataset instances
        #   cdfVLen   list unlimited dimension lengths in each CDF instance
        #   cdfRecVar dictionnary indexed by the record var names; each key holds
        #             a list of the corresponding Variable instance, one for each
        #             cdf file of the file set
        cdf = [cdfm]
        self._cdf = cdf        # Store this now, because dim() method needs it
        cdfVLen = [len(unlimDimId)]
        cdfRecVar = {}
        for v in masterRecVar.keys():
            cdfRecVar[v] = [cdfm.variables[v]]
        
        # Open each remaining file in read-only mode.
        # Make sure each file defines the same record variables as the master
        # and that the variables are defined in the same way (name, shape and type)
        for f in cdfFiles[1:]:
            part = netCDF4_classic.Dataset(f)
            varInfo = part.variables
            for v in masterRecVar.keys():
                # Make sure master rec var is also defined here.
                if v not in varInfo.keys():
                    raise MFDatasetError("record variable %s not defined in %s" % (v, f))

                # Make sure it is a record var.
                vInst = part.variables[v]
                if not part.dimensions[vInst.dimensions[0]].isunlimited():
                    raise MFDataset("variable %s is not a record var inside %s" % (v, f))

                masterDims, masterShape, masterType = masterRecVar[v][:3]
                extDims, extShape, extType = varInfo[v][:3]
                extDims = varInfo[v].dimensions
                extShape = varInfo[v].shape
                extType = varInfo[v].dtype
                # Check that dimension names are identical.
                if masterDims != extDims:
                    raise MFDatasetError("variable %s : dimensions mismatch between "
                                   "master %s (%s) and extension %s (%s)" %
                                   (v, master, masterDims, f, extDims))

                # Check that the ranks are identical, and the dimension lengths are
                # identical (except for that of the unlimited dimension, which of
                # course may vary.
                if len(masterShape) != len(extShape):
                    raise MFDatasetError("variable %s : rank mismatch between "
                                   "master %s (%s) and extension %s (%s)" %
                                   (v, master, len(masterShape), f, len(extShape)))
                if masterShape[1:] != extShape[1:]:
                    raise MFDatasetError("variable %s : shape mismatch between "
                                   "master %s (%s) and extension %s (%s)" %
                                   (v, master, masterShape, f, extShape))

                # Check that the data types are identical.
                if masterType != extType:
                    raise MFDatasetError("variable %s : data type mismatch between "
                                   "master %s (%s) and extension %s (%s)" %
                                   (v, master, masterType, f, extType))

                # Everythig ok.
                cdfRecVar[v].append(vInst)

            cdf.append(part)
            cdfVLen.append(len(part.dimensions[unlimDimName]))

        # Attach attributes to the MFDataset.Dataset instance.
        # A local __setattr__() method is required for them.
        self._cdfFiles = cdfFiles            # list of cdf file names in the set
        self._cdfVLen = cdfVLen              # list of unlimited lengths
        self._cdfTLen = reduce(lambda x, y: x + y, cdfVLen) # total length
        self._cdfRecVar = cdfRecVar          # dictionary of Variable instances for all
                                             # the record variables
        self._dims = cdfm.dimensions
        for dimname, dim in self._dims.items():
            if dim.isunlimited():
                self._dims[dimname] = Dimension(dimname, dim, self._cdfVLen, self._cdfTLen)
        self._vars = cdfm.variables
        for varname,var in self._vars.items():
            if varname in self._cdfRecVar.keys():
                self._vars[varname] = Variable(self, varname, var, unlimDimName)
        self._file_format = []
        for dset in self._cdf:
            self._file_format.append(dset.file_format)

    def __setattr__(self, name, value):
        """override base class attribute creation"""
        self.__dict__[name] = value

    def __getattribute__(self, name):
        if name in ['variables','dimensions','file_format']: 
            if name == 'dimensions': return self._dims
            if name == 'variables': return self._vars
            if name == 'file_format': return self._file_format
        else:
            return netCDF4_classic.Dataset.__getattribute__(self, name)

    def ncattrs(self):
        return self._cdf[0].__dict__.keys()


class Dimension(object):
    def __init__(self, dimname, dim, dimlens, dimtotlen):
        self.dimlens = dimlens
        self.dimtotlen = dimtotlen
    def __len__(self):
        return self.dimtotlen
    def isunlimited(self):
        return True

class Variable(object):
    def __init__(self, dset, varname, var, recdimname):
        self.dimensions = var.dimensions 
        self._dset = dset
        self._mastervar = var
        self._recVar = dset._cdfRecVar[varname]
        self._recdimname = recdimname
        self._recLen = dset._cdfVLen
        self.dtype = var.dtype
        # copy attributes from master.
        for name, value in var.__dict__.items():
            self.__dict__[name] = value
    def typecode(self):
        return self.dtype
    def ncattrs(self):
        return self._mastervar.__dict__.keys()
    def __getattr__(self,name):
        if name == 'shape': return self._shape()
        return self.__dict__[name]
    def _shape(self):
        recdimlen = len(self._dset.dimensions[self._recdimname])
        return (recdimlen,) + self._mastervar.shape[1:]
    def __getitem__(self, elem):
        """Get records from a concatenated set of variables."""
        # Number of variables making up the MFVariable.Variable.
        nv = len(self._recLen)
        # Parse the slicing expression, needed to properly handle
        # a possible ellipsis.
        start, count, stride = netCDF4_classic._buildStartCountStride(elem, self.shape, self.dimensions, self._dset.dimensions)
        # make sure count=-1 becomes count=1
        count = [abs(cnt) for cnt in count]
        if (numpy.array(stride) < 0).any():
            raise IndexError('negative strides not allowed when slicing MFVariable Variable instance')
        # Start, stop and step along 1st dimension, eg the unlimited
        # dimension.
        sta = start[0]
        step = stride[0]
        stop = sta + count[0] * step
        
        # Build a list representing the concatenated list of all records in
        # the MFVariable variable set. The list is composed of 2-elem lists
        # each holding:
        #  the record index inside the variables, from 0 to n
        #  the index of the Variable instance to which each record belongs
        idx = []    # list of record indices
        vid = []    # list of Variable indices
        for n in range(nv):
            k = self._recLen[n]     # number of records in this variable
            idx.extend(range(k))
            vid.extend([n] * k)

        # Merge the two lists to get a list of 2-elem lists.
        # Slice this list along the first dimension.
        lst = zip(idx, vid).__getitem__(slice(sta, stop, step))

        # Rebuild the slicing expression for dimensions 1 and ssq.
        newSlice = [slice(None, None, None)]
        for n in range(1, len(start)):   # skip dimension 0
            newSlice.append(slice(start[n],
                                  start[n] + count[n] * stride[n], stride[n]))
            
        # Apply the slicing expression to each var in turn, extracting records
        # in a list of arrays.
        lstArr = []
        for n in range(nv):
            # Get the list of indices for variable 'n'.
            idx = [i for i,numv in lst if numv == n]
            if idx:
                # Rebuild slicing expression for dimension 0.
                newSlice[0] = slice(idx[0], idx[-1] + 1, step)
                # Extract records from the var, and append them to a list
                # of arrays.
                lstArr.append(netCDF4_classic.Variable.__getitem__(self._recVar[n], tuple(newSlice)))
        
        # Return the extracted records as a unified array.
        if lstArr:
            lstArr = numpy.concatenate(lstArr)
        return lstArr

if __name__ == '__main__':
    from numpy.random import randint
    from numpy.testing import assert_array_equal
    import glob, datetime

    nx = 100
    ydim=5; zdim=10
    data = randint(0,10,size=(nx,ydim,zdim))
    for nfile in range(10):
        if nfile == 0:
            f = netCDF4_classic.Dataset('test'+repr(nfile)+'.nc','w',format='NETCDF3_CLASSIC')
        else:
            f = netCDF4_classic.Dataset('test'+repr(nfile)+'.nc','w')
        f.createDimension('x',None)
        f.createDimension('y',ydim)
        f.createDimension('z',zdim)
        f.history = 'created '+str(datetime.datetime.now())
        x = f.createVariable('x','i',('x',))
        x.units = 'zlotnys'
        dat = f.createVariable('data','i',('x','y','z',))
        dat.name = 'phony data' 
        nx1 = nfile*10; nx2 = 10*(nfile+1)
        x[0:10] = numpy.arange(nfile*10,10*(nfile+1))
        dat[0:10] = data[nx1:nx2]
        f.close()

    files = glob.glob('test*.nc')
    print files
    f = Dataset(files)
    print f.variables
    print f.dimensions
    print f.ncattrs()
    print f.history
    print f.file_format
    print f.variables['data'].shape
    print f.variables['x'].shape
    print f.variables['x'][:]
    print f.variables['x'].ncattrs()
    print f.variables['x'].units
    assert_array_equal(numpy.arange(0,nx),f.variables['x'][:])
    datin = f.variables['data'][4:-4:4,3:5,2:8]
    assert_array_equal(datin,data[4:-4:4,3:5,2:8])