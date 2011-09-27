from commonscripts import elementwiseMultiply,subset,flatten
from optimization import *
from config import default_num_breakpoints

from scipy import linspace, polyval, polyder, interp, poly1d

import matplotlib
#from sys import platform as osname
#if osname=='darwin': matplotlib.use('macosx') #avoid popups when using matploblib to savefig on MacOSX
from pylab import plot,show,savefig,xlabel,ylabel

import re
import logging

class Bid(object):
    """
    Descibes a bid as modeled by :attr:model. (Bids variables change
      with time while :class:`~bidding.PWLmodel` objects do not store
      time dependent information.)
    
    :param model: model for the bid (currently just supports
      :class:`~bidding.PWLmodel` objects).
    :param iden: identifying string for the bidder
    """
    def __init__(self,model,inputvar,iden,statusvar=True):
        vars(self).update(locals())        
    def output(self): 
        return self.model.output(self.variables,self.iden)
    def trueOutput(self,input): return self.model.trueOutput(input)
    def incOutput(self,input):  return self.model.incOutput(input)
    def plotDeriv(self,**kwargs): return self.model.plotDeriv(**kwargs)
    def plot(self,P=None,filename=None,showPW=False):
        plotted=self.model.plot(P,showPW=showPW)
        if filename is not None: savefig(filename)
        return plotted
    def constraints(self):
        '''Create the constraints for a bid by calling its 
        model.constraint() method.'''
        return self.model.constraints(
            variables=self.variables,
            iden=self.iden
            )
    def add_timevars(self): 
        self.variables=self.model.add_timevars(self.iden)
        out=[var for nm,var in self.variables.iteritems()]
        self.variables['inputvar']=self.inputvar
        self.variables['statusvar']=self.statusvar
        return out
        
    def update_vars(self,solution):
        for v in self.variables.iteritems():
            v=value(v, solution)
    def __str__(self): return 'bid {i}'.format(i=self.iden)


def makeModel(polyText,multiplier=1, **kwargs):
    polyCurve=multiplier * parsePolynomial(polyText)
    if isLinear(polyCurve):
        return LinearModel(polyText,multiplier,**kwargs)
    elif isConvex(polyCurve):
        return convexPWLmodel(polyText,multiplier,**kwargs)
    else:
        return PWLmodel(polyText,multiplier,**kwargs)
    
        
    
class PWLmodel(object):
    """
    Describes a piecewise linear model of a polynomial curve.
    
    :param polyText: a string defining the polynomial 
      (see :meth:`~bidding.parsePolynomial` for more on parsing)
    :param multiplier: an optional  multiplier (default is 1) for
      the whole polynomial (used for converting heat rate
      curves to cost curves)
    :param numBreakpoints: number of breakpoints to use when linearizing
      the polynomial (currently the default comes from :mod:`config`)
    :param (min/max)Input: domain of polynomial to consider
    :param (input/output)Nm: names of in/outputs (for plotting)
    """
    def __init__(self,
        polyText='2+10P+0.1P^2',multiplier=1,
        minInput=0,maxInput=10000,
        numBreakpoints=default_num_breakpoints,
        inputNm='x',outputNm='y'):
                
        vars(self).update(locals()) #set the input vars above to be part of class
        self.polyCurve=multiplier * parsePolynomial(polyText) #parse curve
        if isLinear(self.polyCurve): self.numBreakpoints=2 #linear models only need 2 breakpoints
        inDiscrete=linspace(self.minInput, self.maxInput, 1e6) #fine discretization of the curve
        outDiscrete=polyval(self.polyCurve,inDiscrete)
        self.bpInputs = linspace(self.minInput, self.maxInput, self.numBreakpoints) #interpolation to get pwl breakpoints
        self.bpOutputs= interp(self.bpInputs,inDiscrete,outDiscrete)
        self.segments=range(1,len(self.bpInputs))
        
    def plot(self,P=None,filename=None,showPW=True):
        inDiscrete=linspace(self.minInput, self.maxInput, 1e6)
        outDiscrete=polyval(self.polyCurve,inDiscrete)
        if showPW: plot(self.bpInputs,self.bpOutputs,'k.--') #show piecewise linearization
        linePlotted, = plot(inDiscrete,outDiscrete,'-')                      #show continuous curve
        xlabel(self.inputNm)
        ylabel(self.outputNm)
        if P is not None: plot(P,polyval(self.polyCurve,P), 'o', c=linePlotted.get_color(), markersize=8, linewidth=2, alpha=0.7) 
        if filename is not None: savefig(filename)
        return linePlotted
    def plotDeriv(self,P=None,linestyle='-'):
        deriv=polyder(self.polyCurve)
        inDiscrete=linspace(self.minInput, self.maxInput, 1e6)
        outDiscrete=polyval(deriv,inDiscrete)
        linePlotted, =plot(inDiscrete,outDiscrete,linestyle=linestyle)
        if P is not None: plot(P,polyval(deriv,P), 'o', c=linePlotted.get_color(), markersize=8, linewidth=2, alpha=0.7)
        return linePlotted            
    def add_timevars(self,iden):
        variables={}
        #S: segment of cost curve is active
        #F: breakpoint weighting fraction
        for segNum,seg in enumerate(self.segments):  
            name='{iden}_s{segNum}'.format(segNum=segNum,iden=iden)
            variables[name] = newVar(kind='Binary', name=name)
         
        for bpNum,bp in enumerate(self.bpInputs):
            name='{iden}_f{bpNum}'.format( bpNum=bpNum,  iden=iden)
            variables[name] = newVar(low=0,high=1,  name=name)
        return variables 
    def constraints(self,variables,iden):
        """
        Create the constraints for a single time instance of 
          a piecewise linear model. 
          
        :param variables: a dictionary of the variables for the bid
        :param iden: identifying string for the bidder and time interval
        
        :returns: a dictionary of constraints
        """
        constraints=dict()
        status = variables['statusvar']
        inputVar = variables['inputvar']
        S = [variables['{iden}_s{segNum}'.format(segNum=s,iden=iden)] for s in range(len(self.segments))] 
        F = [variables['{iden}_f{bpNum}'.format(bpNum=f,iden=iden)] for f in range(len(self.bpInputs))]

        constraints['oneActiveSegment '+iden]= ( sumVars(S)== status )        
        constraints['fractionSums '+iden]    = ( sumVars(F) == status )
        constraints['computeInput '+iden]    = ( inputVar == sumVars( elementwiseMultiply(F,self.bpInputs) ) )
        constraints['firstSegment '+iden]    = ( F[0]<=S[0] )
        constraints['lastSegment '+iden]     = ( F[-1]<=S[-1] )
        for b in range(1,self.numBreakpoints-1): 
            name='midSegment {iden} b{bnum}'.format(iden=iden,bnum=b)
            constraints[name]                = ( F[b] <= sumVars([S[b-1],S[b]]) )
        return constraints
    def output(self,variables,iden): 
        F = [variables['{iden}_f{bpNum}'.format(bpNum=f,iden=iden)] for f in range(len(self.bpInputs))]
        return sumVars( elementwiseMultiply(F,self.bpOutputs) )
    def trueOutput(self,input): return polyval( self.polyCurve,         value(input) )
    def incOutput(self,input):  return polyval( polyder(self.polyCurve),value(input) )
    def texrepresentation(self,digits=3):
        '''
        Output polynomial to tex-style string.
        
        >>> texrepresentation([ 7,  6, -5])
        '-5+6P+7P^2'    
        '''        
        texstr=''
        exp=0
        for n in reversed(self.polyCurve.c):
            if round(n,digits)==0 and exp!=0: continue
            addChar='+' if n>0 else ''
            if exp>1: texstr+='{pm}{n:0.{d}f}P^{exp}'.format(pm=addChar,n=n,exp=exp,d=digits)
            elif exp==1: texstr+='{pm}{n:0.{d}f}P'.format(pm=addChar,n=n,d=digits)
            elif exp==0: texstr+='{pm}{n:0.{d}f}'.format(pm=addChar,n=n,d=digits)
            exp+=1
        if texstr[0]=='+': texstr=texstr[1:]
        return texstr


class convexPWLmodel(PWLmodel):
    def __init__(self,
        polyText='2+10P+0.1P^2',multiplier=1,
        minInput=0,maxInput=10000,
        numBreakpoints=default_num_breakpoints,
        inputNm='x',outputNm='y'):
        
        def linear_equation(x,m,b): return m*x+b
        def make_lineareq(x1,y1,x2,y2):
            m=(y2-y1)/(x2-x1)
            b=y1-x1*m
            return lambda x: linear_equation(x,m,b)
        
        vars(self).update(locals()) #set the input vars above to be part of class
        self.polyCurve=multiplier * parsePolynomial(polyText) #parse curve
        inDiscrete=linspace(self.minInput, self.maxInput, 1e6) #fine discretization of the curve
        outDiscrete=polyval(self.polyCurve,inDiscrete)
        self.bpInputs = linspace(self.minInput, self.maxInput, self.numBreakpoints) #interpolation to get pwl breakpoints
        self.bpOutputs= interp(self.bpInputs,inDiscrete,outDiscrete)
        self.segment_lines=[]
        for b,x1 in enumerate(self.bpInputs[:-1]):
            x2,y2=self.bpInputs[b+1],self.bpOutputs[b+1]
            y1=self.bpOutputs[b]
            self.segment_lines.append(make_lineareq(x1,y1,x2,y2))
        
    def add_timevars(self,iden):
        variables={}
        name = 'bidCost_'+iden
        variables[name] = newVar(name=name,high=float(max(self.bpOutputs)))
        return variables
    def constraints(self,variables,iden):
        constraints=dict()
        for b,line in enumerate(self.segment_lines): 
            nm='cost_linearized_{}_b{}'.format(iden,b)
            constraints[nm]= variables['bidCost_'+iden] >= line(variables['inputvar'])
        return constraints
    def output(self,variables,iden): return variables['bidCost_'+iden]
    def trueOutput(self,input): return polyval( self.polyCurve,         value(input) )
    def incOutput(self,input):  return polyval( polyder(self.polyCurve),value(input) )
    def plot(self,P=None,filename=None,showPW=True):
        inDiscrete=linspace(self.minInput, self.maxInput, 1e6)
        outDiscrete=polyval(self.polyCurve,inDiscrete)
        if showPW: 
            x=linspace(self.minInput, self.maxInput, 1e6)
            for line in self.segment_lines: plot(x,line(x),'k--') #show piecewise linearization
        plot(inDiscrete,outDiscrete,'-')                      #show continuous curve
        xlabel(self.inputNm)
        ylabel(self.outputNm)
        if P is not None: plot(P,polyval(self.polyCurve,P), 'o', c=linePlotted.get_color(), markersize=8, linewidth=2, alpha=0.7) 
        if filename is not None: savefig(filename)
        else: show()
        return

class LinearModel(PWLmodel):
    def __init__(self,
        polyText='2+10P+0.1P^2',multiplier=1,
        minInput=0,maxInput=10000,
        numBreakpoints=None,
        inputNm='x',outputNm='y'):
        
        self.polyCurve = multiplier * parsePolynomial(polyText)
        self.minInput=minInput
        self.maxInput=maxInput
        
    def add_timevars(self,iden): return dict()
    def constraints(self,variables,iden): return dict()
    def output(self,variables,iden): return polyval( self.polyCurve,variables['inputvar'] )    
    
    
def isLinear(P):
    """Check if a polynomial object is linear using its order attribute."""
    return True if P.order<=1 else False 
def isConvex(P):
    #convexity is complicated: http://plus.maths.org/content/convexity
    #so for now: if all polynomial coefs are positive, call it convex
    return True if all(coef>0 for coef in P.c) else False
    
def parsePolynomial(s):
    """
    Parse a string into a numpy polynomial object.
    Heavily adapted from `<http://bit.ly/polynomialParse>`_.
    
    Can handle simple polynomials (addition and subtraction):     
    
    >>> parsePolynomial('7x^2 + 6x - 5')
    poly1d([ 7,  6, -5])
    
    or with the explicit * multiplier:
    
    >>> parsePolynomial('7*P^2 + 6*P - 5')
    poly1d([ 7,  6, -5])
    
    or even with the terms in some random order: 
    
    >>> parsePolynomial('6*P - 5 + 7*P^2')
    poly1d([ 7,  6, -5])
    """
    
    def parse_n(str):
        '''Parse the number part of a polynomial string term'''
        if not str: return 1
        elif str == '-': return -1
        elif str == '+': return 1
        return eval(str)

    def parse_p(str,powerPattern):
        '''Parse the power part of a polynomial string term'''
        if not str: return 0
        res = powerPattern.findall(str)[0]
        if not res: return 1
        return int(res)
    s=str(s).replace(' ','') #remove all whitespace from string
    m = re.search('[a-zA-Z]+', s) 
    try: varLetter=m.group(0)
    except AttributeError: varLetter='P'
    termPattern = re.compile('([+-]?\d*\.?\d*)\**({var}?\^?\d?)'.format(var=varLetter))
    powerPattern = re.compile('{var}\^?(\d)?'.format(var=varLetter))
    res_dict = {}
    
    for n,p in termPattern.findall(s):
        n,p = n.strip(),p.strip()
        if not n and not p: continue
        n,p = parse_n(n),parse_p(p,powerPattern)
        if res_dict.has_key(p): res_dict[p] += n
        else: res_dict[p] = n
    highest_order = max(res_dict.keys())
    res = [0]*(highest_order+1)
    for key,value in res_dict.items(): res[key] = value
    res.reverse() #reverse the order of the polynomial
    return poly1d(res,variable=varLetter)