from datetime import datetime

date_object = datetime.strptime('Thu, 27 Mar 2025 15:50:00 GMT', "%a, %d %b %Y %H:%M:%S GMT").date()
print(date_object)