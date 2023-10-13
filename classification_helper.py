
import csv
import random

def load_csv(file_path):
    data = []
    with open(file_path, 'r') as file:
        reader = csv.reader(file)
        for row in reader:
            data.append(row)
    return data

def save_csv(file_path, data):
    with open(file_path, 'w', newline='') as file:
        writer = csv.writer(file)
        for row in data:
            writer.writerow(row)

def main():
    input_file = "dataset.csv"
    output_file = "dataset_classified.csv"

    data = load_csv(input_file)
    random.shuffle(data)
    updated_data = []
    stop = False
    try:
        for row in data:
            user = row[0]
            if stop:
                break
            print(user)
            while(True):
                choice = input("Is this a scammer? yes = 1; no= 0: ")
                if choice == "0" or choice == "1":
                    updated_data.append((user, choice))
                    break
                elif choice == "stop":
                    stop = True
                    break
                else:
                    print("Invalid Entry try again")
            save_csv(output_file, updated_data)
    except:
        print("There was an Error, exiting with save")

    save_csv(output_file, updated_data)
    print("Data saved to", output_file)

if __name__ == "__main__":
    main()