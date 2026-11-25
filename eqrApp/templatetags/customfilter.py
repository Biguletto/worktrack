from django import template

register = template.Library()


@register.filter
def replaceBlank(value, stringVal=""):
    return str(value).replace(stringVal, '')
