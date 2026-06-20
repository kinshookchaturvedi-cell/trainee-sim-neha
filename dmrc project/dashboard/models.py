from django.db import models
from django.contrib.auth.models import User
class Layout(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    num_stations = models.IntegerField()
    num_crossovers = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"Layout {self.id} by {self.user.username} ({self.num_stations} Stations)"
class Station(models.Model):
    layout = models.ForeignKey(Layout, on_delete=models.CASCADE)
    number = models.IntegerField()
    def __str__(self):
        return f"Station {self.number} (Layout {self.layout.id})"
class Crossover(models.Model):
    layout = models.ForeignKey(Layout, on_delete=models.CASCADE)
    from_station = models.IntegerField()
    to_station = models.IntegerField()
    position = models.CharField(max_length=10, default='after') # 'before' or 'after'
    def __str__(self):
        return f"Crossover {self.from_station} to {self.to_station} ({self.position}) (Layout {self.layout.id})"
class Depot(models.Model):
    layout = models.ForeignKey(Layout, on_delete=models.CASCADE)
    near_station = models.IntegerField()
    track = models.CharField(max_length=10, default='up') # 'up' or 'down'
    position = models.CharField(max_length=10, default='after') # 'before' or 'after'
    def __str__(self):
        return f"Depot near ST {self.near_station} on {self.track} ({self.position}) (Layout {self.layout.id})"
