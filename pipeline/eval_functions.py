import torch
import os
from utils.datasets import HugoMapped, FulsangDataset, JaulabDataset
from utils.dnn import CNN, FCNN
from torch.utils.data import DataLoader
from utils.functional import correlation, get_subject, check_jaulab_chan, get_params, get_filname, get_Dataset
from statistics import mean
import numpy as np
import pickle
import json

if torch.cuda.is_available():
    device = 'cuda'
else:
    device = 'cpu'

def eval_dnn(model, dataset, subjects, data_path, dst_save_path, mdl_path, key, accuracy=False, population = False, filt = False, filt_path = None):

    print('Evaluating '+model+' on '+dataset+' dataset')

    n_subjects, n_chan, batch_size, _ = get_params(dataset)

    if not isinstance(subjects, list):
        subjects = [subjects]

    eval_results = {}

    for n, subj in enumerate(subjects):

        if dataset == 'jaulab':
            n_chan = check_jaulab_chan(subj)

        test_set = get_Dataset(dataset, data_path, subj, train=False, norm_stim=True, population=population, filt=filt, filt_path=filt_path)
        test_loader = DataLoader(test_set, batch_size, shuffle=False, pin_memory=True)
        
        # OBTAIN MODEL PATH
        filename = dataset
        folder_path = os.path.join(mdl_path , dataset + '_data', model+'_'+key)
        filename = get_filname(folder_path, subj)
    
        model_path = os.path.join(folder_path, filename)

        # LOAD THE MODEL
        if model=='CNN':
            mdl = CNN(F1=8, D=8, F2=64, dropout=0.2, input_channels=n_chan)
        else:
            mdl = FCNN(n_hidden = 3, dropout_rate=0.45, n_chan=n_chan)

        mdl.load_state_dict(torch.load(model_path, map_location=torch.device(device)))
        mdl.to(device)

        # insert the number of samples for performing the circular time shift to obtain the null distribution, in this case between 1 and 2s
        time_shift = 200 if dataset == 'hugo' else 50

        # EVALUATE THE MODEL
        accuracies = []
        with torch.no_grad():
            for i, (x,y) in enumerate(test_loader):
                
                x = x.to(device, dtype=torch.float)
                y = y.to(device, dtype=torch.float)
        
                y_hat, loss = mdl(x)

                acc = correlation(torch.roll(y, time_shift), y_hat)
                # null_acc = correlation(torch.roll(y, time_shift), y_hat)
                accuracies.append(acc.item())

        eval_results[subj] = accuracies

        print(f'Subject {subj} | acc_mean {mean(accuracies)}')

    # SAVE RESULTS
    dest_path = os.path.join(dst_save_path, dataset + '_data')
    if not os.path.exists(dest_path):
        os.makedirs(dest_path)
    filename = model+'_'+key+'_null_distr_Results'
    json.dump(eval_results, open(os.path.join(dest_path, filename),'w'))


def eval_ridge(dataset, subjects, data_path, mdl_path, key, dst_save_path, original = False, filt_path = None):

    n_subjects, n_chan, batch_size, _= get_params(dataset)
    eval_results = {}

    if not isinstance(subjects, list):
        subjects = [subjects]

    for n, subj in enumerate(subjects):

        # CARGA EL MODELO
        model = 'Ridge_'+key if not original else 'Ridge_Original_'+key
        mdl_folder_path = os.path.join(mdl_path, dataset + '_data', model)
        filename = get_filname(mdl_folder_path, subj)
        mdl = pickle.load(open(os.path.join(mdl_folder_path, filename), 'rb'))

        # CARGA EL TEST_SET
        test_dataset = get_Dataset(dataset, data_path, subj, train=False, norm_stim=True, filt=True, filt_path=filt_path)
        if dataset == 'fulsang' or dataset == 'jaulab':
            test_eeg, test_stim = test_dataset.eeg, test_dataset.stima
        else:
            test_eeg, test_stim = test_dataset.eeg, test_dataset.stim
        
        # insert the number of samples for performing the circular time shift to obtain the null distribution, in this case between 1 and 2s
        time_shift = 200 if dataset == 'hugo' else 100

        test_stim = torch.roll(torch.tensor(test_stim), time_shift)

        # EVALÚA EN FUNCIÓN DEL MEJOR ALPHA/MODELO OBTENIDO
        scores = mdl.score_in_batches(test_eeg.T, test_stim[:, np.newaxis], batch_size=batch_size) # ya selecciona el best alpha solo
        eval_results[subj] = [score for score in np.squeeze(scores)]

        print(f'Sujeto {n} | accuracy: {np.mean(scores, axis=0)}')

    dest_path = dest_path = os.path.join(dst_save_path, dataset + '_data')
    if not os.path.exists(dest_path):
        os.makedirs(dest_path)
    filename = 'Ridge_'+key+'_Results' if not original else 'Ridge_Original_'+key+'_Results'
    json.dump(eval_results, open(os.path.join(dest_path, filename),'w'))


# Save the decoding accuracy of each model, only fulsang and jaulab datasets are valid as hugo_data doesn't present two competing stimuli
def decode_attention(model, dataset, subjects, window_len, data_path, mdl_path, dst_save_path, key, population = False, filt = True, filt_path = None):

    n_subjects, n_chan, batch_size, _ = get_params(dataset)
    accuracies = []

    if not isinstance(subjects, list):
        subjects = [subjects] 
    

    print(f'Decoding {model} on {dataset} dataset with a window of {str(window_len/64)}')

    for n, subj in enumerate(subjects):

        if dataset == 'jaulab':
            n_chan = check_jaulab_chan(subj)

        # LOAD DATA
        test_set = get_Dataset(dataset, data_path, subj, train=False, acc=True, norm_stim=True, population=population, filt=filt, filt_path=filt_path)
        test_loader = DataLoader(test_set, batch_size, shuffle=False, pin_memory=True)

        attended_correct = 0

        if model == 'Ridge' or  model == 'Ridge_Original':
            
            # CARGA EL MODELO
            mdl_folder_path = os.path.join(mdl_path, dataset + '_data', model+'_'+key)
            filename = get_filname(mdl_folder_path, subj)
            mdl = pickle.load(open(os.path.join(mdl_folder_path, filename), 'rb'))


            test_eeg, test_stima, test_stimb = test_set.eeg, test_set.stima, test_set.stimb
            scores_a = np.squeeze(mdl.score_in_batches(test_eeg.T, test_stima[:, np.newaxis], batch_size=window_len)) # ya selecciona el best alpha solo
            scores_b = np.squeeze(mdl.score_in_batches(test_eeg.T, test_stimb[:, np.newaxis], batch_size=window_len)) # ya selecciona el best alpha solo

            for i in range(len(scores_a)):
                score_a = scores_a[i]
                score_b = scores_b[i]

                if score_a > score_b:
                    attended_correct += 1

            dec_accuracy = (attended_correct / len(scores_a)) * 100
        
        else:

            # OBTAIN MODEL PATH
            folder_path = os.path.join(mdl_path , dataset + '_data', model+'_'+key)
            filename = get_filname(folder_path, subj)
        
            model_path = os.path.join(folder_path, filename)

            # LOAD THE MODEL
            if model=='CNN':
                mdl = CNN(F1=8, D=8, F2=64, dropout=0.2, input_channels=n_chan)
            else:
                mdl = FCNN(n_hidden = 3, dropout_rate=0.45, n_chan=n_chan)

            mdl.load_state_dict(torch.load(model_path, map_location=torch.device(device)))
            mdl.to(device)

            with torch.no_grad():
                for i, (eeg, stima, stimb) in enumerate(test_loader):
                    
                    eeg = eeg.to(device, dtype=torch.float)
                    stima = stima.to(device, dtype=torch.float)
                    stimb = stimb.to(device, dtype=torch.float)
            
                    preds, loss = mdl(eeg)

                    acc_a = correlation(stima, preds)
                    acc_b = correlation(stimb, preds)

                    if acc_a > acc_b:
                        attended_correct +=1

            dec_accuracy = (attended_correct/len(test_loader)) *100

        accuracies.append(dec_accuracy)
        print(f'Subject: {subj} | acc: {dec_accuracy}')

    dest_path = dest_path = os.path.join(dst_save_path, dataset + '_data', model)
    if not os.path.exists(dest_path):
        os.makedirs(dest_path)
    filename = key+'_'+str(window_len)+'_accuracies'

    json.dump(accuracies, open(os.path.join(dest_path, filename),'w'))
                


        
