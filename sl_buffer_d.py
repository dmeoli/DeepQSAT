import numpy as np


class slBuffer_oneFile:

    def __init__(self, size, fileNo):
        """
        Create sl_buffer for one file at fileNo, that use sparse representation for saving memories.

        Parameters
        ----------
        size: int
            Max number of transitions to store in the buffer. When the buffer
            overflows the old memories are dropped.
        fileNo: int
            the file number for this buffer
        """
        self._maxsize = size
        self.fileNo = fileNo

        # actual store of data and repeats
        self._storage = []
        self._next_idx = 0  # the next index to add samples (for override old samples)
        self._n_repeat = []
        self.sum_n_repeat = 0  # this number tracks the sum of _n_repeat (needs update when samples are added or removed)

        # this is the probability distribution of _n_repeat
        self._prob = None  # (it is None at initialization and when new samples are added)
        # this helps calculate the actual score for each state/Pi pair
        self.mean_step = 0  # (needs to be updated when samples are added or removed).
        self.total_plays = 0
        # VERY IMPORTANT:: mean_step should be averaged by plays, not by steps.
        # it means that if I have two plays, the first play toke 4 steps and the second play took 8 steps.
        # the mean_step should be 6.
        # However I will have 4 additions to the buffer that says steps-4
        #                 and 8 additions to the buffer that says steps-8
        # If I mistakenly did average by steps, I will get mean_step = (4 * 4 + 8 * 8) / (4 + 8) = 6.667
        # which bias the mean_step to a larger value

        # However it seems hard to keep accurate value of mean_step by play, because when storage is full, 
        # data are taken out by step not by play!! 
        # TRICKY: SOLVE LATER. For now, let's just assume no data are taken out.

    def __len__(self):
        return len(self._storage)

    def add_from_Pi_structs(self, Pi_node):
        """
        This function assumes that the Pi_node is the root of the
        Pi_structure generated by MCT in mct_d through self_play
        """
        # first let's update the mean_steps (FIXME: assumes no data are kicked out, when updating mean_step)
        self.total_plays += Pi_node.repeat
        self.mean_step *= ((self.total_plays - Pi_node.repeat) / self.total_plays)
        self.mean_step += (Pi_node.total_steps / self.total_plays)

        # then let's save in those data
        def save_Pi_nodes(a_Pi_node):
            av = a_Pi_node.total_steps / a_Pi_node.repeat
            self.add_uncheck(a_Pi_node.state, a_Pi_node.Pi, av, a_Pi_node.repeat)
            for act in a_Pi_node.children:
                save_Pi_nodes(a_Pi_node.children[act])

        save_Pi_nodes(Pi_node)

    def add_uncheck(self, obs, Pi, step, repeat):
        """
        This function add samples without checking the self.mean_step value
        """
        self._prob = None
        # obs is already 2d sparse array
        data = (obs, Pi, step)
        if self._next_idx >= len(self._storage):  # adding new data new space!
            self._storage.append(data)
            self._n_repeat.append(repeat)
        else:  # adding new data at old space, while removing an old data!
            self._storage[self._next_idx] = data
            self._n_repeat[self._next_idx] = repeat
        self._next_idx = (self._next_idx + 1) % self._maxsize

    def _get_score(self, step):
        return np.tanh((self.mean_step - step) * 3.0 / self.mean_step)

    def _encode_sample(self, idxes):
        obses, Pis, scores = [], [], []
        for i in idxes:
            data = self._storage[i]
            obs, Pi, step = data
            # effort to convert observation (2D sparse) back to 3D numpy"
            obs_2d = obs.toarray()
            obs_3d = np.reshape(obs_2d, [-1, int(obs_2d.shape[1] / 2), 2])

            obses.append(obs_3d)
            Pis.append(Pi)
            # effort to transform step into score
            scores.append(self._get_score(step))

        return np.array(obses, dtype=np.float32), np.array(Pis, dtype=np.float32), np.array(scores, dtype=np.float32)

    def sample(self, batch_size):
        """
        Sample a batch of experiences.

        Parameters
        ----------
        batch_size: int
            How many transitions to sample.

        Returns
        -------
        obs_batch: np.array
            batch of observations
        Pi_batch: np.array
            batch of actions executed given obs_batch
        score_batch: np.array
            rewards received as results of executing act_batch
        """
        if self._prob is None:
            self._prob = np.array(self._n_repeat) / sum(self._n_repeat)
        idxes = np.random.choice(len(self._storage), batch_size, p=self._prob)
        return self._encode_sample(idxes)


class slBuffer_allFile:

    def __init__(self, size, filePath, n_files):
        """
        This is a list of slBuffer_oneFile, which targets all files in filePath
        size: the total size of this list of buffer. Need to divide by the number
        of files to get the size for each slBuffer_oneFile
        n_files: number of files in the filePath
        """
        self.filePath = filePath
        self.n_files = n_files
        self.totalSize = size
        self.eachSize = size // n_files
        self.bufferList = []
        for i in range(n_files):
            self.bufferList.append(slBuffer_oneFile(self.eachSize, i))
        self.sample_round = -1  # this is the round-robin index for sample from the list of slBuffer_oneFile
        self.sample_list = np.zeros(self.n_files, dtype=np.bool)

    def sample(self, batch_size):
        assert np.any(self.sample_list), "Error: sample from an empty sl buffer"
        self.sample_round += 1
        self.sample_round %= self.n_files
        while not self.sample_list[self.sample_round]:
            self.sample_round += 1
            self.sample_round %= self.n_files
        return self.bufferList[self.sample_round].sample(batch_size)

    def add_from_Pi_structs(self, Pi_node):
        """
        This function assumes that the Pi_node is the root of the
        Pi_structure generated by MCT in mct_d through self_play
        """
        file_no = Pi_node.file_no
        self.bufferList[file_no].add_from_Pi_structs(Pi_node)
        self.sample_list[file_no] = True
