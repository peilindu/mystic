#!/usr/bin/env python
#
# Author: Mike McKerns (mmckerns @caltech and @uqfoundation)
# Copyright (c) 1997-2016 California Institute of Technology.
# Copyright (c) 2016-2018 The Uncertainty Quantification Foundation.
# License: 3-clause BSD.  The full license text is available at:
#  - https://github.com/uqfoundation/mystic/blob/master/LICENSE
"""
a global searcher
"""

class Searcher(object):
   #searcher has:
   #    sprayer - an ensemble algorithm
   #    archive - a sampled point archive(s)
   #    retry - max consectutive retries w/o an archive 'miss'
   #    tol - minima comparator rounding precision
   #    _allSolvers - collection of sprayers (for all solver trajectories)
   #
   #searcher (or archive) has:
   #    memtol - memoization rounding precision
   #
   #searcher (or sprayer) has:
   #    seeker - an optimiztion algorithm
   #    map - an enselble map
   #    traj - trajectory configuration (bool)
   #    disp - verbosity configuration (bool)
   #    npts - number of solvers
   #
   #searcher can:
   #    _memoize - apply caching archive to sprayer
   #    _search - perform a single search iteration (the search algorithm ?)
   #    Search - keep performing _search until retry condition is met
   #    UseTrajectories - save all sprayers, thus save all trajectories
   #    Reset - clear caching archive and saved sprayers (thus trajectories)
   #    Trajectories - fetch (step, param, cost) for all solver trajectories
   #    Samples - all sampled points as a n-D array (output is array[-1])
   #    Values - fetch values (model(x)) for sampled points on surface (model)
   #    Coordinates - fetch inputs (x) for sampled points on surface (model)
   #    Minima - fetch {x: model(x)} for all x that minimize model
   #    _summarize - print diagnostics on the value/quantity of solved values
   #
   # searcher (or sprayer) can:
   #    _print - print bestSolution and bestEnergy for each sprayer
   #    _configure (model, bounds, stop, monitor) - configure sprayer
   #    _solve - spray multiple seekers

    def __init__(self, npts=4, retry=1, tol=8, memtol=1, map=None,
              archive=None, sprayer=None, seeker=None, traj=False, disp=False):
        """searcher, which searches for all minima of a response surface

        Input:
          npts - number of solvers in the ensemble
          retry - max consectutive retries w/o an archive 'miss'
          tol - rounding precision for the minima comparator
          memtol - rounding precision for memoization
          map - map used for spawning solvers in the ensemble
          archive - the sampled point archive(s)
          sprayer - the mystic.ensemble instance
          seeker - the mystic.solvers instance
          traj - if True, save the parameter trajectories
          disp - if True, be verbose
        """
        #XXX: better not to use klepto as default? just dict and false cache?
        from klepto.archives import dict_archive as _archive
        from mystic.solvers import BuckshotSolver #XXX: or SparsitySolver?
        from mystic.solvers import PowellDirectionalSolver
        from mystic.pools import SerialPool as Pool
        import sys
        if (sys.hexversion >= 0x30000f0):
            from builtins import map as _map
        else:
            from __builtin__ import map as _map
        del sys
        self.archive = _archive(cached=False) if archive is None else archive
        self.sprayer = BuckshotSolver if sprayer is None else sprayer
        self.seeker = PowellDirectionalSolver if seeker is None else seeker
        self.map = Pool().map if map in (None, _map) else map 
        self.traj = traj
        self.disp = disp

        self.npts = npts # number of solvers
        self.retry = retry   # max consectutive retries w/o a cache 'miss'
        self.tol = tol       # rounding precision
        self.memtol = memtol # memoization rounding precision
        self._allSolvers = []
        self._inv = False    # self-awareness: am I inverted (maximizing)?
        return

    def _print(self, solver, tol=8):
        """print bestSolution and bestEnergy for each sprayer"""
        l = -1 if self._inv else 1
        for _solver in solver._allSolvers:
            bestSol = tuple(round(s, tol) for s in _solver.bestSolution)
            bestRes = round(_solver.bestEnergy, tol)
            print("%s %s" % (bestSol, l*bestRes))

    def _memoize(self, solver, tol=1):
        """apply caching archive to ensemble solver instance"""
        from klepto import inf_cache
        from klepto.keymaps import keymap

        km = keymap()
        ca = inf_cache(tol=tol, ignore=('**','out'),
                       cache=self.archive, keymap=km)

        @ca
        def memo(*args, **kwds):
            return kwds['out']

        l = -1 if self._inv else 1
        for _solver in solver._allSolvers:
            bestSol = tuple(_solver.bestSolution)
            bestRes = float(_solver.bestEnergy)
            memo(*bestSol, out=l*bestRes)  #FIXME: python2.5
        return memo

    def _configure(self, model, bounds, stop=None, monitor=None):
        """generate ensemble solver from objective, bounds, termination, monitor"""
        from mystic.monitors import Monitor
        # configure monitor
        monitor = Monitor() if monitor is None else monitor

        # get dimensions
        ndim = len(bounds)
        _min, _max = zip(*bounds)

        # configure ensemble solver
        self.solver = self.sprayer(ndim, self.npts)
        self.solver.SetNestedSolver(self.seeker)
        self.solver.SetMapper(self.map)
        self.solver.SetObjective(model)
        if stop: self.solver.SetTermination(stop)
        self.solver.SetGenerationMonitor(monitor) #NOTE: may be xy,-z
        self.solver.SetStrictRanges(min=_min, max=_max)
        return

    def _solve(self, id=None, disp=None):
        """run the solver (i.e. search for the minima)"""
        from copy import deepcopy as _copy
        solver = _copy(self.solver) #FIXME: python2.6
        # configure solver
        solver.id = id
        model = solver._cost[1] #FIXME: HACK b/c Solve(model) is required
        # solve
        disp = self.disp if disp is None else disp
#       import time
#       start = time.time()
        solver.Solve(model, disp=disp)
#       print("TOOK: %s" % (time.time() - start))
        return solver

    def _search(self, sid):
        """run the solver, store the trajectory, and cache to the archive"""
        solver = self._solve(sid, self.disp)
        if self.traj: self._allSolvers.append(solver)
        sid += len(solver._allSolvers)
#       self._print(solver, tol=self.tol)
        info = self._memoize(solver, tol=self.memtol).info()
        if self.disp: print(info)
        size = info.size
        return sid, size

    def UseTrajectories(self, traj=True):
        """save all sprayers, thus save all trajectories
        """
        self.traj = bool(traj)
        return

    def Verbose(self, disp=True):
        """be verbose
        """
        self.disp = bool(disp)
        return

    def Search(self, model, bounds, stop=None, monitor=None, traj=None, disp=None):
        """use an ensemble of optimizers to search for all minima

        Inputs:
          model - function z=f(x) to be used as the objective of the Searcher
          bounds - tuple of floats (min,max), bounds on the search region
          stop - termination condition
          monitor - mystic.monitor instance to store parameter trajectories
          traj - klepto.archive to store sampled points
          disp - if true, be verbose
        """
        self.traj = self.traj if traj is None else traj
        self.disp = self.disp if disp is None else disp
        self._configure(model, bounds, stop, monitor)
        count = 0 if self.retry else -1 #XXX: 'rerun' much shorter... unless clear
        sid = 0  # keep track of which solver is which across multiple runs
        while self.retry > count: # stop after retry consecutive no new results
            _size = -1
            size = osize = len(self.archive) #XXX: compare 'size' or 'len(vals)'?
            while size > _size: # stop if no new results
                _size = size
                sid, size = self._search(sid) # uses self.traj and self.disp
            if size == osize: count = count + 1
            else: count = 0

        #NOTE: traj & disp are sticky
        return

    def Reset(self, archive=None, inv=None):
        """clear the archive of sampled points

        Input:
          archive - the sampled point archive(s)
          inv - if True, reset the archive for the inverse of the objective
        """
        if archive is None: self.archive.clear() #XXX: clear the archive?
        self.archive = self.archive if archive is None else archive
        [self._allSolvers.pop() for i in range(len(self._allSolvers))]
        if inv is not None: self._inv = inv

    def Values(self, unique=False):
        """return the sequence of stored response surface outputs

        Input:
          unique: if True, only return unique values

        Output:
          a list of stored response surface outputs
        """
        vals = getattr(self.archive, 'itervalues', self.archive.values)()
        new = set()
        return [v for v in vals if v not in new and not new.add(v)] if unique else list(vals)

    def Coordinates(self, unique=False):
        """return the sequence of stored parameter trajectories

        Input:
          unique: if True, only return unique values

        Output:
          a list of parameter trajectories
        """
        keys = getattr(self.archive, 'iterkeys', self.archive.keys)()
        new = set()
        return [k for k in keys if k not in new and not new.add(k)] if unique else list(keys)

    def Minima(self, tol=None): #XXX: unique?
        """return a dict of (coordinates,values) of all discovered minima

        Input:
          tol: tolerance within which to consider a point a minima

        Output:
          a dict of (coordinates,values) of all discovered minima
        """
        if tol is None: tol=self.tol
        data = self.archive
        _min = max if self._inv else min
        _min = _min(getattr(data, 'itervalues', data.values)())
        return dict((k,v) for (k,v) in getattr(data, 'iteritems', data.items)() if round(v, tol) == round(_min, tol))

    def _summarize(self):
        """provide a summary of the search results"""
        import sys
        if (sys.hexversion >= 0x30000f0):
            from builtins import min as _min
        else:
            from __builtin__ import min as _min
        del sys
        #NOTE: len(size) = # of dirs; len(vals) = # unique dirs
        keys = self.Coordinates()
        vals = self.Values()
        mins = self.Minima()
        name = 'max' if self._inv else 'min'
        min = max if self._inv else _min
        # print the minimum and number of times the minimum was found
        print("%s: %s (count=%s)" % (name, min(mins.values()), len(mins)))
        # print number of minima found, number of unique minima, archive size
        print("pts: %s (values=%s, size=%s)" % (len(set(keys)), len(set(vals)), len(keys)))
        #_i = max(dict(i).values())
        return


    def Trajectories(self): #XXX: better/alternate, read from evalmon?
        """return tuple (iteration, coordinates, cost) of all trajectories
        """
        from mystic.munge import read_trajectories
        if not self.traj:
            try: #NOTE: FRAGILE (if absolute path is not used)
                filename = self.solver._stepmon._filename
                step, param, cost = read_trajectories(filename)
            except AttributeError:
                msg = "a LoggingMonitor or UseTrajectories is required"
                raise RuntimeError(msg)
        else:
            step = []; cost = []; param = [];
            for sprayer in self._allSolvers:  #XXX: slow? better thread.map?
                for seeker in sprayer._allSolvers:
                    values = read_trajectories(seeker._stepmon)
                    step.extend(values[0])
                    param.extend(values[1])
                    cost.extend(values[2])
        #XXX: (not from archive, so) if self._inv: use -cost
        return step, param, cost

    def Samples(self):
        """return array of (coordinates, cost) for all trajectories
        """
        import numpy as np
        xy,xy,z = self.Trajectories()
        xy = np.vstack((np.array(xy).T,z))
        if self._inv: xy[-1,:] = -xy[-1]
        return xy #NOTE: actually xyz

    pass



# EOF
