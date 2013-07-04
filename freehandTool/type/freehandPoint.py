'''
Copyright 2012 Lloyd Konneker

This is free software, covered by the GNU General Public License.
'''
from PySide.QtCore import QPointF


def sign(x):
    ''' Known wart of standard Python: no sign(). '''
    if x > 0:
      return 1
    elif x < 0:
      return -1
    else:
      return 0


class FreehandPoint(QPointF):
  '''
  Real valued point.
  Used in CurveGenerator, where math is real.
  "Freehand" here means: internal to freehand tool, but also real valued.
    
  Methods also return real valued points.
  
  Thin wrapper of implementation in Qt.
  
  For now, in device CS (Qt View.)
  '''
  
  def interval(self, other, fraction):
    ''' 
    Return point fractionally along line from self to other 
    I.E. fractional sect (eg bisect) between vectors.
    '''
    return FreehandPoint( self.x() + fraction * (other.x() - self.x()),
                    self.y() + fraction * (other.y() - self.y())  )


  def cardinalDirectionLeft90(self, other):
    '''
    Return unit (length doesn't matter?), real, vector 90 degrees counterclockwise from other-self,
    but clamped to one of eight cardinal direction (n, nw, w, etc) 
    '''
    return FreehandPoint(-sign(other.y()-self.y()), sign(other.x()-self.x()))
  
  
  