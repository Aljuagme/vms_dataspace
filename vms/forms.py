from django import forms
from .models import Volunteer

class VolunteerForm(forms.ModelForm):
    class Meta:
        model = Volunteer
        fields = ["name", "location", "password", "is_manager", "organization"]



class LoginForm(forms.Form):
    name = forms.CharField(max_length=250)
    password = forms.CharField(widget=forms.PasswordInput)