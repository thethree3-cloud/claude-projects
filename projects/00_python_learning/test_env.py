# Variables and data types in Python

# 1. Numbers: int and float
age = 30            # int (integer)
price = 19.99       # float (decimal number)

# 2. Text: strings
name = "Alice"     # str (string)
message = 'Hello!'

# 3. Boolean values
is_active = True    # bool (True or False)
is_admin = False

# 4. Collections: list, tuple, dict, set
numbers = [1, 2, 3]                 # list
point = (10, 20)                    # tuple
person = {"name": "Alice", "age": 30}  # dict
unique_values = {1, 2, 2, 3}        # set

# Print values and their types
print("age:", age, type(age))
print("price:", price, type(price))
print("name:", name, type(name))
print("is_active:", is_active, type(is_active))
print("numbers:", numbers, type(numbers))
print("point:", point, type(point))
print("person:", person, type(person))
print("unique_values:", unique_values, type(unique_values))

# 5. Change variable values
age = age + 1
name = name + " Smith"
print("Updated age:", age)
print("Updated name:", name)

# 6. Using variables in expressions
total = age * price
print("Total:", total)
