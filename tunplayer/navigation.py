"""Session navigation memory, independent of GTK and provider credentials."""
from collections import OrderedDict
from .jobs import SnapshotCache


class NavigationMemory:
    def __init__(self,limit=32):
        self.pages={};self.positions=OrderedDict();self.limit=limit

    @staticmethod
    def key(request):
        return SnapshotCache.key({k:v for k,v in request.items() if k not in ('revision','advanced')})

    def remember(self,request,offset):
        if request is None:return
        key=self.key(request);self.positions.pop(key,None)
        self.positions[key]=max(0,float(offset))
        while len(self.positions)>self.limit:self.positions.popitem(last=False)

    def position(self,request):return self.positions.get(self.key(request),0)
