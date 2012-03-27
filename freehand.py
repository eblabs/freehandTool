#! /usr/bin/python

'''
Copyright 2012 Lloyd Konneker

This is free software, covered by the GNU General Public License.
'''

'''
Freehand drawing tool.
Input: pointer device (mouse) events.
Output: graphic vector path (lines and splines) which a GUI toolkit renders.
Not a complete app, only a component.
Includes a rudimentary GUI app for testing.
Written in pure Python.

Tags:
- freehand drawing
- computational geometry.
- incremental (dynamic) line tracing.
- Python coroutines.
- pipe of filters.
- GUI toolkit Qt.

Incremental line tracing
========================
Tracing means generating vector graphics from bitmaps.
Incremental, also called dynamic, means generate graphics as a user works,
before the user has completed a stroke (say by mouseReleaseEvent.)
Compare to other freehand tools that draw (not render) pixels until end of tool,
then fit splines to the complete PointerPath and renders the spline.
Here, immediately draw vector graphics (splines and lines.)
Here, look at only a finite tail of the PointerPath.

Goals of incrementality:
- avoid drawing jaggy pixel traces (only to be redrawn later)
- use machine cycles otherwise wasted waiting for pointerEvents

There is a tradeoff: if we spend too much time here, then we fall behind the pointer,
and worse, most GUI toolkits will condense pointer events and only deliver the latest one
(leaving gaps in the input PointerPath).  In other words,  the input will have low resolution.
Then the output suffers, since its quality depends on input resolution.

Filter pipes in Python
======================
This is a series or pipe of filters.
The data between the filters are sequences (streams) of:
- pointer positions, possibly with gaps and possibly with jitter
- pointer positions, without jitter (not implemented)
- pointer turns, between pointer positions not on same axis
- vectors (straight lines) fitting end to end and quaranteed to pass through every PointerPosition (the pixel around it.)
- vectors with adjusted real vertexes (not implemented)
- graphic objects (lines and curves)
- optimized graphic objects (minimal count and minimal error) (not implemented)

The filters are "extended generator" or coroutine or "reverse generators."
Pointer events are pushed (send()) into the pipe and each filter pushes any result to the next filter.
Each filter may maintain history (often just one previous) of its input events,
rolling forward when it recognizes an object that the next filter needs.
The final filter generates finished graphic objects.

potrace
=======
This uses sequence of filters and algorithms from potrace library for tracing bitmap images, by Peter Selinger.
See the potrace paper, it is well written and understandable.

Note some of the filters are optional and this code might not implement them.
See potrace for more description of missing filters.

The main difference to potrace is: potrace input is an image, this input is a PointerPath.

One difference from potrace is that potrace globally finds the best fit.
That is, for a COMPLETE PointerPath, there are many fits, and it would find the best.
Incrementally, we don't have a complete PointerPath,
and we don't have the computing power to incrementally generate a best fit for the partial PointerPath.
We only find the easiest fit, the first one generated.
This could be extended to find a better fit from a set of alternative fits for a short tail of the PointerPath
(where short is defined by how much we can do without lagging the pointer.)
Or you could just use the generated fit as a first approximation, find the best fit, and redraw
(which the user might see as a nudge.)

Another difference from potrace is that potrace generates from continuous paths.
Here the path is generated by the pointer device and may have gaps (if the OS is busy.)
Here detectCorner works despite gaps, i.e. isolates rest of pipe from gaps in the PointerPath. 

Another difference from potrace is that this uses timing.

A property of the potrace algorithm is that it generates cusps for sharp angles on short path segments,
AND ALSO cusps for shallow angles on long path lines.
That is a problem for incremental PointerPath tracing: when user moves the pointer very fast,
it leaves long gaps in the PointerPath, makes for long path lines, and cusps rather than splines.
Also, the generated cusps form a polygon which circumbscribes INSIDE concavities of "real pointer track."
A simple fix MIGHT be to dynamically adjust ALPHAMAX to a value near 4/3 when the pointer is moving very fast.
But it might be a hard limit of implementation in Python: 
there simply is not enough machine resources (in one thread) to do better.
(Another fix might be a threaded implementation.)

Timing
======

The timing of a user's stroke has meaning or intention.
When a user strokes rapidly, they intend a smooth curve.
When a user slows a stroke and turns, they might intend a cusp.
But a slow diagonal generates many PathTurns, which should not generate a cusp.

Ghosting
=======
Since the pipeline lags, ghost a straight LinePathElement from last output of pipeline to current PointerPosition.
Otherwise, the drawn graphic separates from the pointer.

Closing the pipeline
====================
Since the pipeline lags, there is code to shut down the pipeline, generating final graphics to current
PointerPosition.


TODO
====
adapt tool to any GUI kit
jitter filter: doesn't seem to be necessary
curve optimization filter: doesn't seem to be necessary
draw raw mouse track as well as smoothed, for testing
Expose other parameters
Generating single spline, instead of (spline, line) for cusp-like?
Generate a  spline at closing?

Naming
======
generator functions are not classes, but I use use upper case leading letter to emphasize
that calling them returns a generator, whose name begins with lower case letter.

Terminology
===========
(I attempt to use separate terms for distinct concepts!)
Pixels have corners (between sides of a square.)
A PointerPosition is usually coordinates of the upper left corner of a pixel.
A PointerPath, often called a stroke, is a sequence of captured PointerPositions,
from a "pointer device", i.e. mouse, pen, or touch.
(But stroke also refers to a graphics operation of rendering with a brush.)
The "real pointer track" is the shape the user drew, not captured when the pointer moves very fast.
PointerPaths have turns (between subpaths on axis.) Called corners in potrace.
A PathLine is between one or more turns.
Consecutive PathLines have a pivot (points between sequential, non-aligned vectors.)
(Sometimes I use line ambiguously to mean: the math concept, a PathLine, or a LinePathElement.)
The output is a PointerTrack, a sequence of graphic vectors.
Here, it is represented by a QPainterPath inside a QGraphicPathItem.
A PointerTrack comprises a sequence of graphic path items (or elements.)
Graphic path items are LinePathElements or SplinePathElements (beziers.)
Graphic path items have end points.
A cusp is a point between two graphic LinePathElements.  Also called a corner in potrace.
A cusp is usually sharp, but not always an acute angle.
A cusp-like is an end point between a graphic LinePathElement and a SplinePathElement.
When a LinePathElement is between two SplinePathElements, one of the cusp-like is usually sharp.
Distinguish between the PointerPath (bitmap coord input) and the PointerTrack (vector output.)



GUI toolkit adaption
====================
As written, FreehandTool uses Qt.
It could be adapted for other toolkits.
From Qt we use:
- QPointF for points and vectors.
- QLineF for lines
- view and scheme with an API for converting global coords to scheme coords
 and for adding graphic items to scheme
- QGraphicPathItem for the generated drawable graphic (comprising line and curve elements),
to represent user's stroke, 
- OR a set of QGraphicItems for lines and curves

'''

from PySide.QtCore import *
from PySide.QtGui import *
import sys
import traceback


# Parameter: degree of smoothing for curve fitting
# <0 : no smoothing, all straight lines
# >4/3 : no cusps, all splines
# potrace defaults to 1, which seems suitable for bitmap images.
# For freehand drawing, defaults to 1.2
ALPHAMAX = 1.2


# If elapsed time in milliseconds between pointer moves is greater, generate cusp-like instead of smooth.  
MAX_POINTER_ELAPSED_FOR_SMOOTH = 100


'''
Unused cruft: did not use a state machine in CurveGenerator
CURVE_STATE_NONE = 0
LAST_GENERATED_TO_MID = 1
LAST_GENERATED_TO_END = 2
'''


'''
Utility
'''

''' Known wart of standard Python: no sign(). '''
def sign(x):
    if x > 0:
      return 1
    elif x < 0:
      return -1
    else:
      return 0

def crossProduct(p1, p2):
  ''' vector cross product. QPointF does not define. '''
  return p1.x()*p2.y() - p1.y()*p2.x()

def nullLine(point):
  ''' Return a zero length PathLine at a point. '''
  return QLineF(point, point)





class FreehandTool(object):
  
  def __init__(self, scene, view):
    self.turnGenerator = None # Flag, indicates pipe is generating
    # Ghost ungenerated tail of PointerPath with LinePathElement
    self.pathTailGhost = PointerTrackGhost(scene)
    # GUI
    self.scene = scene
    self.view = view
    
    
  def initFilterPipe(self, startPosition):
    ''' 
    Initialize pipe of filters.
    They feed to each other in same order of creation.
     '''
    self.turnGenerator = self.TurnGenerator(startPosition) # call to generator function returns a generator
    self.turnGenerator.send(None) # Execute preamble of generator and pause at first yield
    
    self.lineGenerator = self.LineGenerator(startPosition) 
    self.lineGenerator.send(None) 
    
    self.curveGenerator = self.CurveGenerator(nullLine(startPosition))
    self.curveGenerator.send(None) 
  
  def closeFilterPipe(self):
    '''
    Close generators. 
    They will finally generate SOME of final objects (i.e. turn, PathLine) to current PointerPosition.
    Assume we already received a pointerMoveEvent at same coords of pointerReleaseEvent.
    '''
    if self.turnGenerator is not None:  # Ignore race condition: pointerRelease without prior pointerPress
      self.turnGenerator.close()
      self.turnGenerator = None # Flag pipe is closed
      self.lineGenerator.close()
      self.curveGenerator.close()
  
  
  def _scenePositionFromEvent(self, event):
    ''' Return scene coords mapped from window coords, as a QPointF. '''
    result = self.view.mapToScene(event.x(), event.y())
    #print result
    return result


  def pointerMoveEvent(self, event):
    ''' Feed pointerMoveEvent into a pipe. '''
    try:
      # Generate if pointer button down
      if self.turnGenerator is not None:
        newPosition = self._scenePositionFromEvent(event)
        self.turnGenerator.send(newPosition)  # Feed pipe
        self.pathTailGhost.updateEnd(newPosition)
    except StopIteration:
      '''
      While user is moving pointer, we don't expect pipe to stop.
      If programming error stops pipe, quit app so we can see error trace.
      '''
      sys.exit()
  
  def pointerPressEvent(self, event):
    ''' Start freehand drawing. Init pipe and new graphics item. '''
    self.initFilterPipe(self._scenePositionFromEvent(event))
    
    startPosition = self._scenePositionFromEvent(event)
    # Create contiguous PointerTrack in a new single QGraphicPathItem
    self.path = AddingGraphicsPathItem(startingPoint=startPosition)
    self.scene.addItem(self.path)     # Display pointerTrack
    self.pathTailGhost.showAt(startPosition)
    
    
  
  def pointerReleaseEvent(self, event):
    ''' Stop freehand drawing. '''
    self.closeFilterPipe()
    '''
    CurveGenerator only finally draws to midpoint of current PathLine.
    Add final element to path, a LinePathElement from midpoint to current PointerPosition.
    Note path already ends at the midpoint, don't need to "return" it from close()
    (and close() CANNOT return a value.)
    
    If last generated MidToEnd, we might not need this,
    but that might leave end of PointerTrack one pixel off.
    '''
    self.path.addItem( (self._scenePositionFromEvent(event), ))
    
      
  
  
  '''
  Generator filters
  '''
  
  def TurnGenerator(self, startPosition):
    '''
    Takes PointerPosition on explicit call to send().
    Generates turn positions between lines that lie on a axis (vertical or horizontal).
   
    Qt doesn't have event.time . Fabricate it here.  X11 has event.time.
    '''
    position = None   # if events are: send(None), close(), need this defined
    previousPosition = startPosition
    positionClock = QTime.currentTime()  # note restart returns elapsed
    positionClock.restart()
    # I also tried countPositionsSinceTurn to solve lag for cusp-like
    # print "init turn"
    
    try:
      while True:
        position = (yield)
        positionElapsedTime = positionClock.restart()
        turn = self.detectTurn(previousPosition, position)
        if turn is not None:
          self.lineGenerator.send((turn, positionElapsedTime))
          previousPosition = position  # Roll forward
        else: # path is still on an axis: wait
          pass
    finally:
      # assert position is defined
      if previousPosition != position:
        ''' Have position not sent. Fabricate a turn (equal to position) and send() '''
        self.lineGenerator.send((position, 0))
      print "Closing turn generator"
    
    
  def LineGenerator(self, startPosition):
    '''
    Takes pointer turn on explicit call to send().
    Consumes turns until pixels of PointerPath cannot be approximated by (impinged upon by) one vector.
    Generates vectors on integer plane (grid), not necessarily axial, roughly speaking: diagonals.
    
    Note structure of this filter differs from others:
    - uses three turns (input objects): start, previous, and current.
    - on startup, previousTurn and startTurn are same
    - rolls forward previousTurn every iter, instead of on send().
    '''
    startTurn = startPosition
    previousTurn = startPosition
    constraints = Constraints()
    # directions = Directions()
    #turnClock = QTime.currentTime()  # note restart returns elapsed
    #turnClock.restart()
    try:
      while True:
        turn, positionElapsedTime = (yield)
        #turnElapsedTime = turnClock.restart()
        # print "Turn elapsed", turnElapsedTime
        #line = self.smallestLineFromPath(previousTurn, turn) # TEST 
        line = self.lineFromPath(startTurn, previousTurn, turn, constraints) # ,directions)
        if line is not None:  # if turn not satisfied by vector
          self.curveGenerator.send((line, False))
          # self.labelLine(str(positionElapsedTime), turn)
          startTurn = previousTurn  # !!! current turn is part of next line
        elif positionElapsedTime > MAX_POINTER_ELAPSED_FOR_SMOOTH:
          # User turned slowly, send a forced PathLine which subsequently makes cusp-like graphic
          # Effectively, eliminate generation lag by generating a LinePathElement.
          forcedLine = self.forceLineFromPath(startTurn, previousTurn, turn, constraints)
          self.curveGenerator.send((forcedLine, True))
          # self.labelLine("F" + str(positionElapsedTime), turn)
          startTurn = previousTurn  # !!! current turn is part of next PathLine
        # else current path (all turns) still satisfied by a PathLine: wait
          
        previousTurn = turn  # Roll forward  !!! Every turn, not just on send()
    except Exception as inst:
      # !!! GeneratorExit is a BaseException, not an Exception
      # Unexpected programming errors, which are obscured unless caught
      print "Exception in LineGenerator"
      traceback.print_exc()
    finally:
      if previousTurn != startTurn:
        ''' Have turn not sent. Fabricate a PathLine and send() it now. '''
        self.curveGenerator.send((QLineF(startTurn, previousTurn), 0))
      print "closing line generator"
    
        
  
  def CurveGenerator(self, startLine):
    ''' 
    Takes lines, generates tuples of graphic items (lines or splines).
    Returns spline or cusp (two straight lines) defined between midpoints of previous two lines.
    On startup, previous PathLine is nullLine (!!! not None), but this still works.
    '''
    previousLine = startLine  # null PathLine
    
    try:
      while True:
        line, isLineForced = (yield)
        if isLineForced:
          ''' User speed indicates wants a cusp-like fit, regardless of angle between lines.'''
          curves, pathEndPoint = self.curvesFromLineMidToEnd(previousLine, line)
          previousLine = nullLine(pathEndPoint) # !!! next element from midpoint of nullLine
        else:
          ''' Fit to path, possibly a cusp. '''
          curves, pathEndPoint = self.curvesFromLineMidToMid(previousLine, line)  
          # curves = nullcurveFromLines(previousLine, line) # TEST
          previousLine = line  # Roll forward
        
        # Add results to PointerTrack.
        for item in curves:
          # self.scene.addItem(item)  # add new path comprising this segment
          self.path.addItem(item) # add segment to existing path
        
        self.pathTailGhost.updateStart(pathEndPoint)  # Update ghost to start at end of PointerTrack
       
    except Exception as inst:
      # !!! GeneratorExit is a BaseException, not an Exception
      # Unexpected programming errors, which are obscured unless caught
      print "Exception in CurveGenerator"
      traceback.print_exc()
    finally:
      ''' 
      Last drawn element stopped at midpoint of PathLine.
      Caller must draw one last element from there to current PointerPosition.
      Here we don't know PointerPosition, and caller doesn't *know* PathLine midpoint,
      but path stops at last PathLine midpoint.  IOW  midpoint is *known* by caller as end of PointerTrack.
      
      GeneratorExit exception is still in effect after finally, but caller does not see it,
      and Python does NOT allow it to return a value.
      '''
      print "closing curve generator"

  
  
  '''
  Turn detecting filter.
  '''
  
  def detectTurn(self, position1, position2):
    ''' Return position2 if it turns, i.e. if not on horiz or vert axis with position1, else return None. '''
    if        position1.x() != position2.x() \
          and position1.y() != position2.y()   :
      #print "Turn", position2
      return position2
    else:
      #print "Not turn", position2
      return None 
      
  
  
  '''
  Line fitting filter.
  '''
  
  def smallestLineFromPath(self, turn1, turn2):
    ''' For TESTING: just emit a vector regardless of fit. '''
    return QLineF(turn1, turn2)
  
  def lineFromPath(self, startTurn, previousTurn, currentTurn, constraints, directions=None):
    '''
    Fit a vector to an integer path.
    If no one vector fits path (a pivot): return vector and start new vector.
    Otherwise return None.
    
    Generally speaking, this is a "line simplification" algorithm (e.g. Lang or Douglas-Puecker).
    Given an input path (a sequence of small lines between pointer turns.)
    Output a longer line that approximates path.
    More generally, input line sequence are vectors on a real plane, here they are vectors on a integer plane.
    More generally, there is an epsilon parameter that defines goodness of fit.
    Here, epsilon is half width of a pixel (one half.)
    
    A vector approximates a path (sequence of small lines between pointer turns) until either:
    - path has four directions
    - OR constraints are violated.
    
    Any turn can violate constraints, but more precisely,
    constraint is violated between turns.
    A series of turns need not violate a constraint.
    Only check constraints at each turn,
    then when constraints ARE violated by a turn,
    calculate exactly which PointerPosition (between turns) violated constraints.
    '''
    '''
    I found that for PointerTracks, this happens so rarely it is useless.
    Only useful for traced bitmap images?
    
    directions.update(previousTurn, currentTurn)
    if len(directions) > 3:
      # a path with four directions can't be approximated with one vector
      # TODO, end point is starting pixel of segment ???
      print "Four directions"
      self.resetLineFittingFilter()
      # Note end is previousTurn, not current Turn
      return QLineF(startTurn, previousTurn)
    else:
    '''
    # Vector from startTurn, via many turns, to currentTurn
    vectorViaAllTurns = currentTurn - startTurn
    if constraints.isViolatedBy(vector=vectorViaAllTurns):
      # print "Constraint violation", constraints, "vector", vectorViaAllTurns
      result = self.interpolateConstraintViolating(startTurn=startTurn,
         lastSatisfyingTurn=previousTurn,
         firstNonsatisfingTurn=currentTurn)
      # reset
      constraints.__init__()
      # directions.reset()
      return result
    else:
      constraints.update(vectorViaAllTurns)
      return None # Defer, until subsequent corner
   
   
  def interpolateConstraintViolating(self, startTurn, lastSatisfyingTurn, firstNonsatisfingTurn):
    '''
    Interpolate precise violating pixel position
    Return a PathLine.
    
    This version simply returns PathLine to lastSatisfyingTurn (a null interpolation.)
    potrace does more, a non-null interpolation.
    '''
    return QLineF(startTurn, lastSatisfyingTurn)

  
  def forceLineFromPath(self, startTurn, previousTurn, currentTurn, constraints, directions=None):
    ''' 
    Force a PathLine to currentTurn, regardless of constraints. 
    Note this is a PathLine, not a LinePathElement.
    '''
    constraints.__init__()
    # print "Force PathLine", startTurn, currentTurn
    return QLineF(startTurn, currentTurn)
    
    
    
  '''
  Curve fitting filter.
  Fit a spline to two vectors.
  '''
  
  def nullcurveFromLines(self, line1, line2):
    ''' 
    Return QGraphicsItem to represent tail of PointerPath.
    FOR TESTING. Generates a simple LinePathElement (instead of SplinePathElement.)
    After all, a straight line is a curve with null curvature.
    '''
    return (QGraphicsLineItem(line1), ) # Note lag one PathLine
    # TODO broken, needs to return pathEndPoint
    

  def curvesFromLineMidToMid(self, line1, line2):
    '''
    Return a tuple of QGraphicsItems that fit midpoints of two lines.
    Two cases, depend on angle between lines:
    - acute angle: cusp: returns two lines.
    - obtuse angle: not cusp: return spline that smoothly fits bend.
    '''
    
    # aliases for three points defined by two abutting PathLines
    point1 = line1.p1()
    point2 = line1.p2()
    point3 = line2.p2()
    
    # midpoints of PathLines
    # midpoint1 = self.interval(1/2.0, point2, point1)  # needed if creating QGraphicPathItem directly
    midpoint2 = self.interval(1/2.0, point3, point2)
    
    denom = self.ddenom(point1, point3);
    if denom != 0.0:
      dd = abs(self.areaOfParallelogram(point1, point2, point3) / denom)
      if dd > 1:
        alpha = (1 - 1.0/dd)/0.75
      else : 
        alpha = 0
    else:
        alpha = 4/3.0

    if alpha > ALPHAMAX:
      return self.createCusp(cuspPoint=point2, endPoint=midpoint2)
    else:
      alpha = self.clampAlpha(alpha)
      '''
      Since first control point for this spline is on same PathLine
      as second control point for previous spline,
      said control points are colinear and joint between consecutive splines is smooth.
      '''
      return self.createSplinePathElement(controlPoint1=self.interval(0.5+0.5*alpha, point1, point2), 
                              controlPoint2=self.interval(0.5+0.5*alpha, point3, point2), 
                              endPt=midpoint2)
        
  def curvesFromLineMidToEnd(self, line1, line2):
    '''
    Return a tuple (two or three) of QGraphicsItems that fit midpoint of first PathLine to end of second PathLine.
    '''
    midToMidCurves, pathEndPoint = self.curvesFromLineMidToMid(line1, line2)
    finalEndPoint = line2.p2()
    #print "Mid to end"
    midToEnd = self.createLinePathElement(finalEndPoint) # implicitly starts at current path end
    # !!! for catenation, make tuple by "(foo, )"
    return midToMidCurves + (midToEnd, ), finalEndPoint
    
      


  '''
  Auxiliary functions for curvesFromLineMidToMid() etc
  '''
  
  def createLinePathElement(self, endPoint):
    ''' 
    Create our representation of a LinePathElement from current end of PointerTrack to endPoint.
    Mangle to signature of AddingGraphicsPathItem.addItem()
    A LinePathElement is a tuple comprising single endpoint.
    (the starting point of LinePathElement is implicitly the end of PointerTrack.)
    '''
    return (endPoint, )


  def createCusp(self, cuspPoint, endPoint):
    '''
    Create sharp cusp. Return two straight LinePathElements,
    from midpoints of two generating lines (not passed end of path, and endPoint) 
    to point where generating lines meet (cuspPoint)
    Note we already generated graphic item to first midpoint,
    and will subsequently generate graphic item from second midpoint.
    '''
    print "cusp <<<"
    '''
    Equivalent if adding to scene: 
    line1 = QGraphicsLineItem(QLineF(midpoint1, point2))
    line2 = QGraphicsLineItem(QLineF(point2, midpoint2))
    '''
    '''
    Return tuple of path elements, each element a LinePathElement.
    Also return end point of PointerTrack.
    '''
    return (self.createLinePathElement(cuspPoint), self.createLinePathElement(endPoint)), endPoint
  
  
  def createSplinePathElement(self, controlPoint1, controlPoint2, endPt):
    ''' 
    Mangle to signature of AddingGraphicsPathItem.addItem().
    Return tuple of path elements.  Here, a single element comprising three tuple for spline.
    Also return end of PointerTrack.
    !!! Note start point is not present.
    '''
    print "curve"
    """
    Equivalent if adding to scene:
    return (self.getCurveQGraphicsItem(startPt=midpoint1, 
      controlPt1=self.interval(.5+.5*alpha, point1, point2), 
      controlPt2=self.interval(.5+.5*alpha, point3, point2), 
      endPt=midpoint2), ) # !!! Python idiom to force a tuple
    """
    return ((controlPoint1, controlPoint2, endPt), ), endPt
  
  
  def interval(self, fraction, point1, point2):
    ''' 
    Return point fractionally along line from point1 to point2 
    I.E. fractional sect (eg bisect) between vectors.
    '''
    return QPointF( point1.x() + fraction * (point2.x() - point1.x()),
                    point1.y() + fraction * (point2.y() - point1.y())  )
  
  
  '''
  ddenom/areaOfParallelogram have property that the square of radius 1 centered
  at p1 intersects line p0p2 iff |areaOfParallelogram(p0,p1,p2)| <= ddenom(p0,p2)
  '''
      
  def ddenom(self, p0, p1):
    ''' ??? '''
    r = self.cardinalDirectionLeft90(p0, p1)
    return r.y()*(p1.x()-p0.x()) - r.x()*(p1.y()-p0.y());
    
    
  def areaOfParallelogram(self, p0, p1, p2):
    '''
    Vector cross product of vector point1 - point0 and point2 - point0
    I.E. area of the parallelogram defined by these three points.
    Scalar.
    '''
    return (p1.x()-p0.x()) * (p2.y()-p0.y()) - (p2.x()-p0.x()) * (p1.y()-p0.y())
  
  def cardinalDirectionLeft90(self, p0, p1):
    '''
    Return unit (length doesn't matter?) vector 90 degrees counterclockwise from p1-p0,
    but clamped to one of eight cardinal direction (n, nw, w, etc) 
    '''
    return QPointF(-sign(p1.y()-p0.y()), sign(p1.x()-p0.x()))
    
  
  def clampAlpha(self, alpha):
    if alpha < 0.55:  return 0.55
    elif alpha > 1:   return 1
    else:             return alpha


  def getCurveQGraphicsItem(self, startPt, controlPt1, controlPt2, endPt):
    '''
    In Qt > v4.0 there is no QGraphicsCurveItem, only QGraphicsPathItem with a curve in its path.
    '''
    path = QPainterPath()
    path.moveTo(startPt)
    path.cubicTo(controlPt1, controlPt2, endPt)
    return QGraphicsPathItem(path)
    
  def labelLine(self, string, position):
    ''' For testing '''
    text = self.scene.addSimpleText(string)
    text.setPos(position)
    


class Directions(object):
  '''
  Dictionary of cardinal directions (N, S, E, W) taken by a path.
  Understands how to compute a direction between two turns.
  '''
  def __init__(self):
    self.dict = {}
  
  def __len__(self):
    return len(self.dict)
    
  def update(self, turn1, turn2):
    vectorBetweenTurns = turn2 - turn1
    direction = (3 + 3*sign(vectorBetweenTurns.x()) + sign(vectorBetweenTurns.y()))/2
    self.dict[direction] = 1
    
  def reset(self):
    self.__init__()
    # super(Directions, self).__init__()
    
  


class Constraints(object):
  '''
  Constraints comprise pair of vectors.
  Their origin is near starting position, which is same as starting turn.
  It may help to think of them as crossing, from extremities of first pixel corners,
  to "opposite", but nearest to centerline, corner of extreme pixel in path.
  In other words, constraints define a funnel where future pixels can be
  and there still exist an approximating vector touching all pixels. 
  '''
  def __init__(self):
    # Null vectors
    self.constraintLeft = QPointF(0,0)
    self.constraintRight = QPointF(0,0)
  
  def __repr__(self):
    return "Left " + str(self.constraintLeft) + " Right " + str(self.constraintRight)
  
  def isViolatedBy(self, vector=None):
    ''' Does vector violate constraints? i.e. lie outside constraint vectors '''
    return crossProduct(self.constraintLeft, vector) < 0 or crossProduct(self.constraintRight, vector) > 0
  
  
  def update(self, v):
    '''
    Update constraints given vector v.
    Vector v is via all turns: many turns may have satisfied constraints.
    Assert: Vector v satisfies constraints.
    '''
    '''
    Potrace checked for no constraints as follows.
    It never occurs when turns are input since it takes three pixels to make a turn.
    If you take out turnGenerator, this might make sense.
   
    if abs(v.x())<=1 and abs(v.y())<=1 :
      print "No constraints."
      pass
    else:
    '''
    # print "Updating constraints"
    offset = QPointF( v.x() + (1 if v.y() >= 0 and (v.y()>0 or v.x()<0) else -1 ),
                      v.y() + (1 if v.x() <= 0 and (v.x()<0 or v.y()<0) else -1 ) )
    if crossProduct(self.constraintLeft, offset) >= 0 :
      self.constraintLeft = offset
      
    offset = QPointF( v.x() + (1 if v.y() <= 0 and (v.y()<0 or v.x()<0) else -1 ),
                      v.y() + (1 if v.x() >= 0 and (v.x()>0 or v.y()<0) else -1 ) )
    if crossProduct(self.constraintRight, offset) <= 0 :
      self.constraintRight = offset


class PointerTrackGhost(object):
  '''
  A ghost for freehand drawing.
  Line between current PointerPosition and last PointerTrack path segment generated, which lags.
  Finally replaced by a path segment.
  Hidden when user not using freehand tool.
  '''
  def __init__(self, scene):
    self.lineItem = QGraphicsLineItem(QLineF(QPointF(0,0), QPointF(0,0)))
    self.lineItem.hide()
    self.start = None
    self.end = None
    scene.addItem(self.lineItem)
  
  def showAt(self, initialPosition):
    self.start = initialPosition
    self.end = initialPosition
    self.lineItem.setLine(QLineF(self.start, self.end))
    self.lineItem.show()
    
  def updateStart(self, point):
    self.start = point
    self.lineItem.setLine(QLineF(self.start, self.end))
    
  def updateEnd(self, point):
    self.end = point
    self.lineItem.setLine(QLineF(self.start, self.end))
    
  def hide(self, point):
    self.lineItem.hide()



class AddingGraphicsPathItem(QGraphicsPathItem):
  ''' 
  Item in scene that is a path and supports adding segments.
  Specific to Qt GUI toolkit.
  '''
  def __init__(self, startingPoint):
    super(AddingGraphicsPathItem, self).__init__()
    path = QPainterPath(startingPoint)
    self.setPath(path)

    
  def addItem(self, item):
    ''' 
    Add GraphicPathElement (line or spline) to path.
    Item is tuple:
    - line: (endpoint)
    - curve: ( cp1, cp2, endpoint)
    '''
    path = self.path()
    # hack, non-polymorphic
    if len(item) == 3: # three tuple for cubic from end of path
      path.cubicTo(*item)
    elif len(item) == 1:  # tuple with one endpoint of line
      path.lineTo(*item)
    # !!! path is NOT an alias for self.path() now, they differ.  Hence:
    self.setPath(path)
    # No need to invalidate or update display, at least for Qt
  
  # TESTING: helps see segments.  Not necessary for production use.
  def paint(self, painter, styleOption, widget):
    ''' Reimplemented to paint elements in alternating colors '''
    path = self.path()  # alias
    pathEnd = None
    i = 0
    while True:
      try:
        element = path.elementAt(i)
        # print type(element), element.type
        if element.isMoveTo():
          pathEnd = QPointF(element.x, element.y)
          i+=1
        elif element.isLineTo():
          newEnd = QPointF(element.x, element.y)
          painter.drawLine(pathEnd, newEnd)
          pathEnd = newEnd
          i+=1
        elif element.isCurveTo():
          # Gather curve data, since is spread across elements of type curveElementData
          cp1 = QPointF(element.x, element.y)
          element = path.elementAt(i+1)
          cp2 = QPointF(element.x, element.y)
          element = path.elementAt(i+2)
          newEnd = QPointF(element.x, element.y)
          # create a subpath, since painter has no drawCubic method
          subpath=QPainterPath()
          subpath.moveTo(pathEnd)
          subpath.cubicTo(cp1, cp2, newEnd)
          painter.drawPath(subpath)
          
          pathEnd = newEnd
          i+=3
        else:
          print "unhandled path element", element.type
          i+=1
        if i >= path.elementCount():
          break
      except Exception as inst:
        print inst
        break
        
      # Alternate colors
      if i%2 == 1:
        painter.setPen(Qt.blue)
      else:
        painter.setPen(Qt.red)
      
  


