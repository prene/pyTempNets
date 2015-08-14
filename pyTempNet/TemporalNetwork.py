# -*- coding: utf-8 -*-
"""
Created on Thu Feb 19 11:49:39 2015
@author: Ingo Scholtes, Roman Cattaneo

(c) Copyright ETH Zürich, Chair of Systems Design, 2015
"""

import igraph
import numpy as np
from collections import defaultdict

import bisect

from pyTempNet.Utilities import RWTransitionMatrix
from pyTempNet.Utilities import StationaryDistribution

class TemporalNetwork:
    """A class representing a temporal network consisting of a sequence of time-stamped edges"""
    
    def __init__(self,  sep=',', tedges = None, twopaths = None):
        """Constructor generating an empty temporal network"""
        
        self.tedges = []
        nodes_seen = defaultdict( lambda:False )
        self.nodes = []

        # Some index structures to quickly access tedges by time, target and source        
        self.time = defaultdict( lambda: list() )
        self.targets = defaultdict( lambda: dict() )
        self.sources = defaultdict( lambda: dict() )        

        # An ordered list of time-stamps (invalidated as soon as links are changed)
        self.ordered_times = []

        self.tedges = []

        if tedges is not None:
            print('Building indexing data structures ...', end='')
            for e in tedges:
                self.time[e[2]].append(e)
                self.targets[e[2]].setdefault(e[1], []).append(e)
                self.sources[e[2]].setdefault(e[0], []).append(e)
                if not nodes_seen[e[0]]:
                    nodes_seen[e[0]] = True
                if not nodes_seen[e[1]]:
                    nodes_seen[e[1]] = True
            self.tedges = tedges
            self.nodes = list(nodes_seen.keys())
            print('finished.')

            print('Sorting time stamps ...', end = '')
            self.ordered_times = np.sort(list(self.time.keys()))
            print('finished.')

        self.twopaths = []
        self.twopathsByNode = defaultdict( lambda: dict() )
        self.twopathsByTime = defaultdict( lambda: dict() )
        self.tpcount = -1

        """The separator character to be used to generate second-order nodes"""
        self.separator = sep

        """The maximum time difference between consecutive links to be used 
        for extraction of time-respecting paths of length two"""
        self.delta = 1                                    

        # Generate index structures if temporal network is constructed from two-paths
        if twopaths is not None:
            t = 0
            for tp in twopaths:
                self.twopaths.append(tp)
                s = tp[0]
                v = tp[1]
                d = tp[2]

                if s not in self.nodes:
                    self.nodes.append(s)
                if v not in self.nodes:
                    self.nodes.append(v)
                if d not in self.nodes:
                    self.nodes.append(d)
  
                self.twopathsByNode[v].setdefault(t, []).append(tp)
                t +=1
            self.tpcount = len(twopaths)        

        # Cached instances of first- and second-order aggregate networks
        self.g1 = 0
        self.g2 = 0
        self.g2n = 0
        

    def addEdge(self, source, target, ts):
        """Adds a directed time-stamped edge (source,target;time) to the temporal network. To add an undirected 
            time-stamped link (u,v;t) at time t, please call addEdge(u,v;t) and addEdge(v,u;t).
        
        @param source: naem of the source node of a directed, time-stamped link
        @param target: name of the target node of a directed, time-stamped link
        @param time: (integer) time-stamp of the time-stamped link
        """
        e = (source, target, ts)
        self.tedges.append(e)
        if source not in self.nodes:
            self.nodes.append(source)
        if target not in self.nodes:
            self.nodes.append(target)

        # Add edge to index structures
        self.time[ts].append(e)
        self.targets[ts].setdefault(target, []).append(e)
        self.sources[ts].setdefault(source, []).append(e)

        # Reorder time stamps
        self.ordered_times = np.sort(list(self.time.keys()))
        
        self.InvalidateTwoPaths()


    def InvalidateTwoPaths(self):
        """Invalidates all cached two-path data and aggregate networks"""
        
        # Invalidate indexed data 
        self.tpcount = -1
        self.twopaths = []
        self.twopathsByNode = defaultdict( lambda: dict() )
        self.twopathsByTime = defaultdict( lambda: dict() )
        self.g1 = 0
        self.g2 = 0
        self.g2n = 0
        

    def vcount(self):
        """Returns the total number of different vertices active across the whole evolution of the temporal network. 
        This number corresponds to the number of nodes in the (first-order) time-aggregated network."""
        return len(self.nodes)

        
    def ecount(self):
        """Returns the number of time-stamped edges (u,v;t) in this temporal network"""
        return len(self.tedges)


    def setMaxTimeDiff(self, delta):
        """Sets the maximum time difference delta between consecutive links to be used for 
        the extraction of time-respecting paths of length two (two-paths). If two-path structures
        and/or second-order networks have previously been computed, this method will invalidate all
        cached data if the new delta is different from the old one (for which the data have been computed)

        @param delta: Indicates the maximum temporal distance up to which time-stamped links will be 
        considered to contribute to time-respecting path. For (u,v;3) and (v,w;7) a time-respecting path (u,v)->(v,w) 
        will be inferred for all 0 < delta <= 4, while no time-respecting path will be inferred for all delta > 4. 
        If the max time diff is not specific speficially, the default value of delta=1 will be used, meaning that a 
        time-respecting path u -> v will only be inferred if there are *directly consecutive* time-stamped 
        links (u,v;t) (v,w;t+1).
        """
        
        if delta != self.delta:
            # Set new value and invalidate two-path structures
            self.delta = delta
            self.InvalidateTwoPaths()
    

    def getInterEventTimes(self):
        """Returns a numpy array containing the time differences between
            consecutive time-stamped links (by any node)"""

        timediffs = []
        for i in range(1, len(self.ordered_times)):
            timediffs += [self.ordered_times[i] - self.ordered_times[i-1]]
        return np.array(timediffs)


    def extractTwoPaths(self):
        """Extracts all time-respecting paths of length two in this temporal network. The two-paths 
        extracted by this method will be used in the construction of second-order time-aggregated 
        networks, as well as in the analysis of causal structures of this temporal network. If an explicit 
        call to this method is omitted, it will be run with the current parameter delta set in the 
        TemporalNetwork instance (default: delta=1) whenever two-paths are needed for the first time.
        Once two-paths have been computed, they will be cached and reused until the maximum time difference 
        delta is changed.
        """

        print('Extracting two-paths for delta =', self.delta)

        self.tpcount = -1
        self.twopaths = []
        self.twopathsByNode = defaultdict( lambda: dict() )
        self.twopathsByTime = defaultdict( lambda: dict() )

        # Frequent accesses to stack variable are faster than instance variables
        dt = self.delta

        # For each time stamp in the data set ... 
        for i in range(len(self.ordered_times)):
            t = self.ordered_times[i]
            max_ix = bisect.bisect_right(self.ordered_times, t+dt)-1

            # For each possible middle node v (i.e. all target nodes at time t) ... 
            for v in self.targets[t]:

                # For all time stamps in the range (t, t+delta] ...
                for j in range(i+1, max_ix+1):
                    future_t = self.ordered_times[j]
                    # First check if v is source of a time-stamped link at time last_t
                    if v in self.sources[future_t]:
                        # For all possible IN-edges that end with v
                            for e_in in self.targets[t][v]:
                                # Combine with all OUT-edges that start with v
                                for e_out in self.sources[future_t][v]:
                                    s = e_in[0]
                                    d = e_out[1]
                                    indeg_v = len(self.targets[t][v])
                                    outdeg_v = len(self.sources[future_t][v])    
                                    # For each s create a weighted two-path tuple
                                    # (s, v, d, weight)

                                    # TODO: Add support for weighted time-stamped links

                                    two_path = (s,v,d, float(1)/(indeg_v*outdeg_v))

                                    self.twopaths.append(two_path)
                                    self.twopathsByNode[v].setdefault(t, []).append(two_path) 
                                    self.twopathsByTime[t].setdefault(v, []).append(two_path)
        
        # Update cached values
        g1 = 0
        g2 = 0
        g2n = 0        
        self.tpcount = len(self.twopaths)

        
    def TwoPathCount(self):
        """Returns the total number of time-respecting paths of length two which have
            been extracted from the time-stamped edge sequence."""
        
        # If two-paths have not been extracted yet, do it now
        if self.tpcount == -1:
            self.extractTwoPaths()

        return self.tpcount
    
    def igraphFirstOrder(self, all_links=False, force=False):
        """Returns the first-order time-aggregated network
           corresponding to this temporal network. This network corresponds to 
           a first-order Markov model reproducing the link statistics in the 
           weighted, time-aggregated network."""
        
        if self.g1 != 0 and not force:
            return self.g1
           
        # If two-paths have not been extracted yet, do it now
        if self.tpcount == -1:
            self.extractTwoPaths()

        self.g1 = igraph.Graph(n=len(self.nodes), directed=True)
        self.g1.vs["name"] = self.nodes

        edge_list = {}

        # Gather all edges and their (accumulated) weights in a directory        
        if all_links:
            for e in self.tedges:
                edge_list[(e[0], e[1])] = edge_list.get((e[0], e[1]), 0) + 1
        else:                    
            for tp in self.twopaths:
                key1 = (tp[0], tp[1])
                key2 = (tp[1], tp[2])
                # get key{1,2} with default value 0 from edge_list directory
                edge_list[key1] = edge_list.get(key1, 0) + tp[3]
                edge_list[key2] = edge_list.get(key2, 0) + tp[3]
            
        # adding all edges at once is much faster as igraph updates internal
        # data structures after each vertex/edge added
        self.g1.add_edges( edge_list.keys() )
        self.g1.es["weight"] = list(edge_list.values())
        
        return self.g1


    def igraphSecondOrder(self):
        """Returns the second-order time-aggregated network
           corresponding to this temporal network. This network corresponds to 
           a second-order Markov model reproducing both the link statistics and 
           (first-order) order correlations in the underlying temporal network.
           """

        if self.g2 != 0:
            return self.g2

        if self.tpcount == -1:
            self.extractTwoPaths()

        print('Constructing second-order aggregate network ...', end='')

        # create vertex list and edge directory first
        vertex_list = []
        edge_dict = {}
        sep = self.separator
        for tp in self.twopaths:
            n1 = str(tp[0])+sep+str(tp[1])
            n2 = str(tp[1])+sep+str(tp[2])
            vertex_list.append(n1)
            vertex_list.append(n2)
            key = (n1, n2)
            edge_dict[key] = edge_dict.get(key, 0) + tp[3]
            
        # remove duplicate vertices by building a set
        vertex_list = list(set(vertex_list))
        
        # build 2nd order graph
        self.g2 = igraph.Graph( n=len(vertex_list), directed=True )
        self.g2.vs["name"] = vertex_list
        
        # add all edges in one go
        self.g2.add_edges( edge_dict.keys() )
        self.g2.es["weight"] = list(edge_dict.values())

        print('finished.')

        return self.g2


    def igraphSecondOrderNull(self):
        """Returns a second-order null Markov model 
           corresponding to the first-order aggregate network. This network
           is a second-order representation of the weighted time-aggregated network. In order to 
           compute the null model, the strongly connected component of the second-order network 
           needs to have at least two nodes.          
           """
        if self.g2n != 0:
            return self.g2n

        g2 = self.igraphSecondOrder().components(mode='STRONG').giant()
        n_vertices = len(g2.vs)

        assert(n_vertices>1)
        
        T = RWTransitionMatrix( g2 )
        pi = StationaryDistribution(T)
        
        # Construct null model second-order network
        self.g2n = igraph.Graph(directed=True)
        # NOTE: This ensures that vertices are ordered in the same way as in 
        # NOTE: the empirical second-order network
        for v in self.g2.vs():
            self.g2n.add_vertex(name=v["name"])
        
        ## TODO: This operation is the bottleneck for large data sets!
        ## TODO: Only iterate over those edge pairs, that actually are two paths!
        edge_dict = {}
        vertices = g2.vs()
        sep = self.separator
        for i in range(n_vertices):
            e1 = vertices[i]
            e1name = e1["name"]
            a,b = e1name.split(sep)
            for j in range(i+1, n_vertices):
                e2 = vertices[j]
                e2name = e2["name"]
                a_,b_ = e2name.split(sep)
                
                # Check whether this pair of nodes in the second-order 
                # network is a *possible* forward two-path
                if b == a_:
                    w = np.abs(pi[e2.index])
                    if w>0:
                        edge_dict[(e1name, e2name)] = w
                        
                if b_ == a:
                    w = np.abs(pi[e1.index])
                    if w>0:
                        edge_dict[(e2name, e1name)] = w
        
        # add all edges to the graph in one go
        self.g2n.add_edges( edge_dict.keys() )
        self.g2n.es["weight"] = list(edge_dict.values())
        
        return self.g2n


    def ShuffleEdges(self, l=0):        
        """Generates a shuffled version of the temporal network in which edge statistics (i.e.
        the frequencies of time-stamped edges) are preserved, while all order correlations are 
        destroyed.
        
        @param l: the length of the sequence to be generated (in terms of the number of time-stamped links.
            For the default value l=0, the length of the generated shuffled temporal network will be equal to that of 
            the original temporal network. 
        """
        tedges = []
        
        if self.tpcount == -1:
            self.extractTwoPaths()
        
        if l==0:
            l = 2*int(len(self.tedges)/2)
        for i in range(l):
            # Here we simply shuffle the order of all edges
            edge = self.tedges[np.random.randint(0, len(self.tedges))]
            tedges.append((edge[0], edge[1], i))
        t = TemporalNetwork(sep=',', tedges=tedges)
        t.nodes = self.nodes
            
        return t
        
        
    def ShuffleTwoPaths(self, l=0):
        """Generates a shuffled version of the temporal network in which two-path statistics (i.e.
        first-order correlations in the order of time-stamped edges) are preserved
        
        @param l: the length of the sequence to be generated (in terms of the number of time-stamped links.
            For the default value l=0, the length of the generated shuffled temporal network will be equal to that of 
            the original temporal network. 
        """
        
        tedges = []
        
        if self.tpcount == -1:
            self.extractTwoPaths()
        
        t = 0
        
        times = list(self.twopathsByTime.keys())
        
        if l==0:
            l = len(self.tedges)
        for i in range(int(l/2)):
            # Chose a time uniformly at random
            rt = times[np.random.randint(0, len(self.twopathsByTime))]
            
            # Chose a node active at that time uniformly at random
            rn = list(self.twopathsByTime[rt].keys())[np.random.randint(0, len(self.twopathsByTime[rt]))]
            
            # Chose a two path uniformly at random
            paths = self.twopathsByTime[rt][rn]
            tp = paths[np.random.randint(0, len(paths))]
            
            tedges.append((tp[0], tp[1], t))
            t += 1
            tedges.append((tp[1], tp[2], t))
            t += 1
            
        tempnet = TemporalNetwork(sep=',', tedges=tedges)
        return tempnet