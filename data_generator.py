import math
import random
import numpy as np
from classification_helper import load_csv, save_csv

class DataGen:
    
    def __init__(self) -> None:
        pass
    
    def gen_gfx_suffix(data):
        # Create a view of the first column as a string array
        first_column = data[:, 0].astype(str)

        # Initialize an empty list for the new first column
        new_data = []
        unique_values = set()

        for s in first_column:
            if "gfx" not in s:
                new_value = s + "_gfx"
                if new_value not in unique_values:
                    unique_values.add(new_value)
                    new_data.append([new_value, '1'])  # Make sure '1' is a string
        return np.array(new_data)
    
    def randomize_numbers(data):
        new_data = []
        for i in range(len(data)):
            unique_values = set()
            for j in range(10):
                old_d = data[i, 0].replace(f"{j}", f"{random.randint(0, 9)}")
                new_d = data[i, 0].replace(f"{j}", f"{random.randint(0, 9)}")
                if old_d not in unique_values:
                    unique_values.add(old_d)
                    new_data.append([old_d, data[i, 1]])
                if new_d not in unique_values:
                    unique_values.add(new_d)
                    new_data.append([new_d, data[i, 1]])
        new_data = np.array(new_data)
        return new_data
                
    def gen_new_dim_inverse(data):
        if data.shape[1] != 2:
            raise ValueError("Input matrix must have 2 columns")

        complementary_column = 1 - data[:, 1].astype(int)  # Convert the column to int before subtraction
        result_matrix = np.column_stack((data, complementary_column))

        return result_matrix

    def convert_column_to_int(data, column_index):
        data[:, column_index] = data[:, column_index].astype(int)
        return data

    def gen_gfx_prefix(data):
            # Create a view of the first column as a string array
        first_column = data[:, 0].astype(str)

        # Initialize an empty list for the new first column
        new_data = []
        unique_values = set()

        for s in first_column:
            if "gfx" not in s:
                new_value = "gfx_" + s
                if new_value not in unique_values:
                    unique_values.add(new_value)
                    new_data.append([new_value, '1'])  # Make sure '1' is a string
        return np.array(new_data)
    
    def full_name_gen(file_path_names, file_path_surnames, amount, gen_trailing_numbers = False, insert = ''):
        surnames = load_csv(file_path_surnames)
        names = load_csv(file_path_names)
        picked_names = []
        for i in range(amount):
            name = f"{random.choice(names)[0]}{insert}{random.choice(surnames)[0]}"
            if(gen_trailing_numbers):
                picked_names.append([name, 1])
                for _ in range(random.randint(0, 4)):
                    name += f"{random.randint(0, 9)}"
                picked_names.append([name, 1])
            else:
                picked_names.append([name, 1])
        return np.array(picked_names)
    
    def name_gen(file_path_names, amount, gen_trailing_numbers = True):
        names = load_csv(file_path_names)
        picked_names = []
        for i in range(amount):
            name = f"{random.choice(names)[0]}"
            if(gen_trailing_numbers):
                for _ in range(random.randint(2, 5)):
                    name += f"{random.randint(0, 9)}"
                picked_names.append([name, 1])
            else:
                picked_names.append([name, 1])
        return np.array(picked_names)
    
    def gen_char(data: np.ndarray, char = ''):
        first_column: np.ndarray = data[:, 0].astype(str)

        # Initialize an empty list for the new first column
        new_data = []
        unique_values = set()
        for s in first_column:
            index = random.randint(0,len(s)-1)
            is_scammer = data[np.where(first_column == s),1][0][0]
            new_value = s[:index] + char + s[index:]
            if new_value not in unique_values:
                unique_values.add(new_value)
                new_data.append([new_value, is_scammer])
        return np.array(new_data)
    
    
    def longest_string_length(arr):
        if arr.size == 0:
            return 0  # Handle empty array case
        
        first_column = arr[:, 0]  # Extract the first column
        max_length = len(max(first_column, key=len))  # Find the length of the longest string

        return max_length   
if __name__ == "__main__":
    
    arr = np.array(load_csv("data_for_gen.csv"))
    raw_data_len = len(arr)
    raw_data_scam = np.count_nonzero(arr == "1")
    
    users = arr[arr[:,1] == '0']
    users = np.concatenate((users, DataGen.gen_char(users, char='_')))
    #arr = np.concatenate((arr, DataGen.gen_char(users, char='_')))
    arr = np.concatenate((arr, DataGen.randomize_numbers(users)), axis=0)
    arr = np.concatenate((arr, DataGen.randomize_numbers(arr)), axis=0)
    arr = np.concatenate((arr, DataGen.name_gen("names.csv", 200, gen_trailing_numbers=True)))
    arr = np.concatenate((arr, DataGen.full_name_gen("names.csv", "surnames.csv", 200)))
    arr = np.concatenate((arr, DataGen.full_name_gen("names.csv", "surnames.csv", 200, gen_trailing_numbers=True)))
    #arr = np.concatenate((arr, DataGen.full_name_gen("names.csv", "surnames.csv", 1000, gen_trailing_numbers=True, insert = '_')))
    arr = np.concatenate((arr, DataGen.randomize_numbers(arr)), axis=0)
    arr = np.concatenate((arr, DataGen.randomize_numbers(arr)), axis=0)
    arr = np.concatenate((arr, DataGen.randomize_numbers(arr)), axis=0)
    arr = np.concatenate((arr, DataGen.gen_gfx_prefix(arr)),axis=0)
    arr = np.concatenate((arr, DataGen.gen_gfx_suffix(arr)), axis=0)
    arr = np.concatenate((arr, [["abcdefghijklm", "0"],["nopqrtsuvwxyz", "0"], ["0987654321", "0"]]), axis=0)
    print(
        f'''{math.floor((np.count_nonzero(arr == "1")/len(arr))*100)}% of the Dataset are scammers
        Of that {raw_data_scam} were not generated
        The item generation equates to {len(arr)-raw_data_len} items
        Which brings the total data set to a lenght of {len(arr)}'''.replace("  ", ""))
    print(f"Please use {DataGen.longest_string_length(arr)} as the Squence length")
    save_csv("generated_data.csv", arr)