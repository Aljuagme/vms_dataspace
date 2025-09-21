from functools import wraps
from django.shortcuts import redirect

def volunteer_login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if "volunteer_id" not in request.session:
            return redirect("vms:login")
        return view_func(request, *args, **kwargs)
    return wrapper
