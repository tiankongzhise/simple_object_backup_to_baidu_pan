import a
print(f'b:__name__:{__name__}')

def b():
    print(f'b_b():{__name__}')

if __name__ == '__main__':
    b()
