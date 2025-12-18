from django.db import models

class ScrapeRun(models.Model):

    source_domain = models.CharField(max_length=100, default="ihg.com")
    created_at = models.DateTimeField(auto_now_add=True)

    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lon = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    nights_scraped = models.IntegerField(null=True, blank=True)
    adults = models.IntegerField(null=True, blank=True)
    rooms = models.IntegerField(null=True, blank=True)

    raw_payload = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"{self.source_domain} run #{self.id}"


class Hotel(models.Model):
    hotel_code = models.CharField(max_length=20, unique=True)
    hotel_name = models.CharField(max_length=300, blank=True, null=True)

    address = models.CharField(max_length=600, blank=True, null=True)
    city = models.CharField(max_length=120, blank=True, null=True)
    state_province = models.CharField(max_length=120, blank=True, null=True)
    country = models.CharField(max_length=120, blank=True, null=True)
    country_code = models.CharField(max_length=10, blank=True, null=True)

    property_url = models.URLField(blank=True, null=True)

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    currency = models.CharField(max_length=3, null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    raw = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"{self.hotel_code} | {self.hotel_name or ''}"


class HotelImage(models.Model):
    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='images')
    url = models.URLField()
    sort_order = models.IntegerField(default=0)

    class Meta:
        unique_together = (('hotel', 'url'),)
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.hotel.hotel_code} img"


class RoomCategory(models.Model):
    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name="room_categories")
    category_code = models.CharField(max_length=50)
    description = models.TextField(null=True, blank=True)

    class Meta:
        unique_together = (('hotel', 'category_code'),)


    def __str__(self):
        return f"{self.hotel.hotel_code} {self.category_code}"


class RoomRate(models.Model):

    room_category = models.ForeignKey(RoomCategory, on_delete=models.CASCADE, related_name="rates")
    stay_date = models.DateField(null=True, blank=True)

    cash_rate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    starting_rate_points = models.IntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, null=True, blank=True)

    class Meta:
        unique_together = (('room_category', 'stay_date'),)
        indexes = [
            models.Index(fields=['stay_date']),
        ]

    def __str__(self):
        return f"{self.room_category.hotel.hotel_code} {self.room_category.category_code} {self.stay_date}"





# Create your models here.
