import string

letters = string.ascii_letters

username = "bobby"
for x in username:
    if x not in letters:
        print("WRONG")
    
print("YUH")