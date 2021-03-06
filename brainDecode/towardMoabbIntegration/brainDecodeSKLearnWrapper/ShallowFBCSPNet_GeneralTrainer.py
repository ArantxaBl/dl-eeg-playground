

"""
BrainDecode encapsulation into a sklearn classifier

BrainDecode
ref: https://github.com/robintibor/braindecode
ref: Schirrmeister, R. T., Springenberg, J. T., Fiederer, L. D. J., Glasstetter, M., Eggensperger, K., Tangermann, M., ... & Ball, T. (2017). 
     Deep learning with convolutional neural networks for EEG decoding and visualization. Human brain mapping, 38(11), 5391-5420.


"""

from sklearn.base import BaseEstimator, ClassifierMixin
from braindecode.datautil.signal_target import SignalAndTarget
from braindecode.models.shallow_fbcsp import ShallowFBCSPNet
from torch import nn
from braindecode.torch_ext.util import set_random_seeds    
from torch import optim
import torch
from braindecode.torch_ext.util import np_to_var, var_to_np
from braindecode.datautil.iterators import get_balanced_batches
import torch.nn.functional as F
import numpy as np
from numpy.random import RandomState
from random import randint

#Load optimizer. You can find hyperparameters in the link below.  
#http://pytorch.org/docs/master/optim.html

        
class ShallowFBCSPNet_GeneralTrainer(BaseEstimator, ClassifierMixin):  
    
    
    
    """
        Initialize the parameters of the network
        Full list of parameters described in 
        ref: https://robintibor.github.io/braindecode/source/braindecode.models.html
    """
    def __init__(self, 
                n_filters_time=10,
                filter_time_length=75,
                n_filters_spat=5,
                pool_time_length=60,
                pool_time_stride=30,
                nb_epoch=160):
                    
        # random generator
        self.rng = RandomState(None)
        # init meta info
        self.cuda = torch.cuda.is_available()
        set_random_seeds(seed=randint(1,20180505), cuda=self.cuda) 
        
        # copy all network parameters
        self.n_filters_time=n_filters_time
        self.filter_time_length=filter_time_length
        self.n_filters_spat=n_filters_spat
        self.pool_time_length=pool_time_length
        self.pool_time_stride=pool_time_stride
        self.nb_epoch = nb_epoch
        
        return 

    """
        Fit the network
        Params:
            X, data array in the format (...)
            y, labels
        ref: http://danielhnyk.cz/creating-your-own-estimator-scikit-learn/
    """
    def fit(self, X, y):
        
        # define a number of train/test trials
        nb_train_trials = int(np.floor(7/8*X.shape[0]))
        
        # split the dataset
        self.train_set = SignalAndTarget(X[:nb_train_trials], y=y[:nb_train_trials])
        self.test_set = SignalAndTarget(X[nb_train_trials:], y=y[nb_train_trials:])
        
        # number of classes and input channels
        n_classes = np.unique(y).size
        in_chans = self.train_set.X.shape[1]
        
        # final_conv_length = auto ensures we only get a single output in the time dimension
        self.model = ShallowFBCSPNet(
                                in_chans=in_chans, 
                                n_classes=n_classes,
                                input_time_length=self.train_set.X.shape[2],
                        
                                n_filters_time=self.n_filters_time,
                                filter_time_length=self.filter_time_length,
                                n_filters_spat=self.n_filters_spat,
                                pool_time_length=self.pool_time_length,
                                pool_time_stride=self.pool_time_stride,
                                
                                final_conv_length='auto'
                                
                                ).create_network()
        
        # setup model for cuda
        if self.cuda:
            self.model.cuda()
        
        # setup optimizer
        self.optimizer = optim.Adam(self.model.parameters())
        
        
        # array that tracks results
        self.loss_rec = np.zeros((self.nb_epoch,2))
        self.accuracy_rec = np.zeros((self.nb_epoch,2))
                
        # run all epoch
        for i_epoch in range(self.nb_epoch):
            
            self._batchTrain(i_epoch, self.train_set)
            self._evalTraining(i_epoch, self.train_set, self.test_set)

        return self

    
    """
        Training iteration, train the network on the train_set
        Params:
            i_epoch, current epoch iteration
            train_set, training set
    """
    def _batchTrain(self, i_epoch, train_set):
    
    
        # get a set of balanced batches
        i_trials_in_batch = get_balanced_batches(len(train_set.X), self.rng, shuffle=True,
                                                batch_size=32)
    
        # Set model to training mode
        self.model.train()
        
        # go through all batches
        for i_trials in i_trials_in_batch:
            
            # Have to add empty fourth dimension to X
            batch_X = train_set.X[i_trials][:,:,:,None]
            batch_y = train_set.y[i_trials]
            
            net_in = np_to_var(batch_X)
            net_target = np_to_var(batch_y)
            
            # if cuda, copy to cuda memory
            if self.cuda:
                net_in = net_in.cuda()
                net_target = net_target.cuda()
            
            # Remove gradients of last backward pass from all parameters
            self.optimizer.zero_grad()
            # Compute outputs of the network
            outputs = self.model(net_in)
            # Compute the loss
            loss = F.nll_loss(outputs, net_target)
            # Do the backpropagation
            loss.backward()
            # Update parameters with the optimizer
            self.optimizer.step()
        
        return
        
        
    """
        Evaluation iteration, computes the performance the network
        Params:
            i_epoch, current epoch iteration
            train_set, training set
    """
    def _evalTraining(self, i_epoch, train_set, test_set):
        
    
        # Print some statistics each epoch
        self.model.eval()
        print("Epoch {:d}".format(i_epoch))
        
        sets = {'Train' : 0, 'Test' : 1}
        
        # run evaluation on both train and test sets
        for setname, dataset in (('Train', train_set), ('Test', test_set)):
            
            # get balanced sets
            i_trials_in_batch = get_balanced_batches(len(dataset.X), self.rng, batch_size=32, shuffle=False)
            
            outputs = []
            net_targets = []
            
            # for all trials in set
            for i_trials in i_trials_in_batch:
                
                # adapt datasets
                batch_X = dataset.X[i_trials][:,:,:,None]
                batch_y = dataset.y[i_trials]
                
                # apply some conversion
                net_in = np_to_var(batch_X)
                net_target = np_to_var(batch_y)
                
                # convert
                if self.cuda:
                    net_in = net_in.cuda()
                    net_target = net_target.cuda()
                
                net_target = var_to_np(net_target)
                output = var_to_np(self.model(net_in))
                outputs.append(output)
                net_targets.append(net_target)
                
            net_targets = np_to_var(np.concatenate(net_targets))
            outputs = np_to_var(np.concatenate(outputs))
            loss = F.nll_loss(outputs, net_targets)
     
            print("{:6s} Loss: {:.5f}".format(setname, float(var_to_np(loss))))
            
            self.loss_rec[i_epoch, sets[setname]] = var_to_np(loss)
            predicted_labels = np.argmax(var_to_np(outputs), axis=1)
            accuracy = np.mean(dataset.y  == predicted_labels)
            
            print("{:6s} Accuracy: {:.1f}%".format(setname, accuracy * 100))
            self.accuracy_rec[i_epoch, sets[setname]] = accuracy
        
        return

    def predict(self, X):
        self.model.eval()
        
        #i_trials_in_batch = get_balanced_batches(len(X), self.rng, batch_size=32, shuffle=False)
        
        outputs = []
        
        for i_trials in i_trials_in_batch:
            batch_X = dataset.X[i_trials][:,:,:,None]
            
            net_in = np_to_var(batch_X)
            
            if self.cuda:
                net_in = net_in.cuda()
            
            output = var_to_np(self.model(net_in))
            outputs.append(output)
            
        return outputs


