import numpy as np
import pfh_readsnap
#import parameters as par
import config as cfg
from astropy.table import Table
from astropy.io import ascii
import constants as const
import pdb
import sys

import fsps 
from datetime import datetime
from datetime import timedelta


from multiprocessing import Pool




class Stars:
    def __init__(self,mass,metals,positions,age,sed_bin=[-1,-1,-1],lum=-1):
        self.mass = mass
        self.metals = metals
        self.positions = positions
        self.age = age
        self.sed_bin = sed_bin
        self.lum = lum

    def info(self):
        return(self.mass,self.metals,self.positions,self.age,self.sed_bin,self.lum)






def star_list_gen():
    print 'reading in stars particles for SPS calculation'

    sdir = cfg.par.hydro_dir
    snum = cfg.par.Gadget_snap_num

    #NEW STARS
    new_stars_dict = pfh_readsnap.readsnap(sdir,snum,4)
    mass = new_stars_dict['m']*cfg.par.unit_mass*const.msun #g (as par.unit_mass is in msun)
    metals = new_stars_dict['z']
    positions = new_stars_dict['p']*cfg.par.unit_length*const.pc*1.e3 #cm (as par.unit_length is kpc)
    age = new_stars_dict['age'] #Gyr (per phopkins)


    median_metallicity = np.median(metals)
  
    nstars = len(age)
    print 'number of new stars =',nstars
    

    #create the stars_list full of Stars objects
    stars_list = []
    for i in range(nstars):
        stars_list.append(Stars(mass[i],metals[i],positions[i],age[i]))

    

    #ASSIGN DISK AND BULGE STARS - note, if these don't exist, it will
    #just pull whatever bogus values it can from particle types 2 and
    #3
    #DISK STARS
    disk_stars_dict = pfh_readsnap.readsnap(sdir,snum,2)
    nstars_disk = len(disk_stars_dict['m'])
    disk_positions = disk_stars_dict['p']*cfg.par.unit_length*const.pc*1.e3 #cm (as par.unit_length is kpc)
    disk_masses = disk_stars_dict['m']*cfg.par.unit_mass*const.msun #g (as par.unit_mass is in msun)
    
    #BULGE STARS
    bulge_stars_dict = pfh_readsnap.readsnap(sdir,snum,3)
    nstars_bulge = len(bulge_stars_dict['m'])
    bulge_positions = bulge_stars_dict['p']*cfg.par.unit_length*const.pc*1.e3 #cm (as par.unit_length is kpc)
    bulge_masses = bulge_stars_dict['m']*cfg.par.unit_mass*const.msun #g (as par.unit_mass is in msun)
    
    bulgestars_list = []
    for i in range(nstars_bulge):
        bulgestars_list.append(Stars(bulge_masses[i],0.02,bulge_positions[i],cfg.par.bulge_stars_age))
            
      
        
    '''
    else: 
        #we just assign bogus values to the disk and bulge masses: equate them to the newstar values
        disk_masses = mass
        bulge_masses = mass
    '''
    
        
        
    #create the bulge_list full of BulgeStars objects
    bulgestars_list = []
    for i in range(nstars_bulge):
        bulgestars_list.append(Stars(bulge_masses[i],0.02,bulge_positions[i],cfg.par.bulge_stars_age))
            
    diskstars_list = []
    for i in range(nstars_disk):
        diskstars_list.append(Stars(disk_masses[i],0.02,disk_positions[i],cfg.par.disk_stars_age))






    return stars_list,diskstars_list,bulgestars_list

def allstars_sed_gen(stars_list,diskstars_list,bulgestars_list):


    #NOTE this part is just for the gadget simulations - this will
    #eventually become obviated as it gets passed into a function to
    #populate the stars_list with objects as we start to feed in new
    #types of simulation results.

    nstars = len(stars_list)
    nstars_disk = len(diskstars_list)
    nstars_bulge = len(bulgestars_list)


    #get just the wavelength array
    sp = fsps.StellarPopulation(tage=stars_list[0].age,imf_type=1,sfh=0)
    spec = sp.get_spectrum(tage=stars_list[0].age)
    nu = 1.e8*const.c/spec[0]
    nlam = len(nu)



    #initialize the process pool and build the chunks
    p = Pool(processes = cfg.par.n_processes)
    nchunks = cfg.par.n_processes


    chunk_start_indices = []
    chunk_start_indices.append(0) #the start index is obviously 0

    delta_chunk_indices = int(nstars / nchunks)
    print 'delta_chunk_indices = ',delta_chunk_indices
    
    for n in range(1,nchunks):
        chunk_start_indices.append(chunk_start_indices[n-1]+delta_chunk_indices)

    '''
    chunk_start_indices = list(np.fix(np.arange(0,nstars,np.fix(nstars/nchunks))))
    #because this can result in too many chunks sometimes given the number of processors:
    chunk_start_indices = chunk_start_indices[0:nchunks]
    '''
    list_of_chunks = []
    for n in range(nchunks):
        stars_list_chunk = stars_list[chunk_start_indices[n]:chunk_start_indices[n]+delta_chunk_indices]
        #if we're on the last chunk, we might not have the full list included, so need to make sure that we have that here
        if n == nchunks-1: 
            stars_list_chunk = stars_list[chunk_start_indices[n]::]

        list_of_chunks.append(stars_list_chunk)
    
    

        print 'Entering Pool.map multiprocessing'
    t1=datetime.now()
    chunk_sol = p.map(newstars_gen, [arg for arg in list_of_chunks])
    
    t2=datetime.now()
    print 'Execution time for SED generation in Pool.map multiprocessing = '+str(t2-t1)

    
    stellar_fnu = np.zeros([nstars,nlam])
    star_counter=0
    for i in range(nchunks):
        fnu_list = chunk_sol[i] #this is a list of the stellar_fnu's returned by that chunk
        for j in range(len(fnu_list)):
            stellar_fnu[star_counter,:] = fnu_list[j,:]
            star_counter+=1




    p.close()
    p.terminate()
    p.join()


    stellar_nu = nu

    #calculate the SED for disk stars; note, this gets calculated
    #whether or not disk stars actually exist.  if they don't exist,
    #bogus values for the disk age and metallicity are assigned based
    #on whatever par.disk_stars_age and metallicity are.  it's no big
    #deal since these SEDs don't end up getting added to the model in
    #source_creation as long as COSMOFLAG == True.  

    sp = fsps.StellarPopulation(tage = cfg.par.disk_stars_age,imf_type=1,sfh=0)
    spec = sp.get_spectrum(tage=cfg.par.disk_stars_age)
    disk_fnu = spec[1]

    #calculate the SED for bulge stars
    sp = fsps.StellarPopulation(tage = cfg.par.bulge_stars_age,imf_type=1,sfh=0)
    spec = sp.get_spectrum(tage=cfg.par.bulge_stars_age)
    bulge_fnu = spec[1]
    

    #return positions,disk_positions,bulge_positions,mass,stellar_nu,stellar_fnu,disk_masses,disk_fnu,bulge_masses,bulge_fnu
    return stellar_nu,stellar_fnu,disk_fnu,bulge_fnu





















def newstars_gen(stars_list):
    #the newstars (particle type 4; so, for cosmological runs, this is all
    #stars) are calculated in a separate function with just one argument so that it is can be fed 
    #into pool.map for multithreading.
    

    #first figure out how many wavelengths there are
    sp = fsps.StellarPopulation(tage=stars_list[0].age,imf_type=1,sfh=0)
    spec = sp.get_spectrum(tage=stars_list[0].age)
    nu = 1.e8*const.c/spec[0]
    


    nlam = len(nu)

    stellar_nu = np.zeros([nlam])
    stellar_fnu = np.zeros([len(stars_list),nlam])
    
  
    
    #DEBUG DEBUG DEBUG 
    #for now we don't have a metallicity in the sps calculations
    print '========================='
    print 'WARNING: METALLICITIES NOT ACCOUNTED FOR IN STELLAR SEDS'
    print '========================'
    
    

    #calculate the SEDs for new stars
    for i in range(len(stars_list)):
        
        sp = fsps.StellarPopulation(tage=stars_list[i].age,imf_type=1,sfh=0)
        spec = sp.get_spectrum(tage=stars_list[i].age)

        stellar_nu[:] = 1.e8*const.c/spec[0]
        stellar_fnu[i,:] = spec[1]

    return stellar_fnu



