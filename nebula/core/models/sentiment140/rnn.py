import torch

from nebula.core.models.nebulamodel import NebulaModel


class Sentiment140ModelRNN(NebulaModel):
    def __init__(
        self,
        input_channels=3,
        num_classes=10,
        learning_rate=1e-3,
        metrics=None,
        confusion_matrix=None,
        seed=None,
    ):
        super().__init__(input_channels, num_classes, learning_rate, metrics, confusion_matrix, seed)

        self.config = {"beta1": 0.851436, "beta2": 0.999689, "amsgrad": True}

        self.example_input_array = torch.zeros(1, 1, 28, 28)
        self.learning_rate = learning_rate

        self.embedding_dim = 300
        self.hidden_dim = 256
        self.n_layers = 1
        self.bidirectional = True
        self.output_dim = num_classes

        self.encoder = torch.nn.LSTM(
            self.embedding_dim,
            self.hidden_dim,
            num_layers=self.n_layers,
            bidirectional=self.bidirectional,
            dropout=0.5,
            batch_first=True,
        )
        self.fc = torch.nn.Linear(self.hidden_dim * 2, self.output_dim)
        self.dropout = torch.nn.Dropout(0.5)

        self.criterion = torch.nn.CrossEntropyLoss()

        self.l1 = torch.nn.Linear(28 * 28, 256)
        self.l2 = torch.nn.Linear(256, 128)
        self.l3 = torch.nn.Linear(128, num_classes)

        self.epoch_global_number = {"Train": 0, "Validation": 0, "Test": 0}

    def forward(self, x):
        packed_output, (hidden, cell) = self.encoder(x)
        hidden = self.dropout(torch.cat((hidden[-2, :, :], hidden[-1, :, :]), dim=1))
        out = self.fc(hidden)
        out = torch.log_softmax(out, dim=1)
        return out

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters(), lr=self.learning_rate)
        return optimizer
