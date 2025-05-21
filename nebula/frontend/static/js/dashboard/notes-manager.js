// Notes Manager Module
const NotesManager = {
    init() {
        this.bindEvents();
    },

    bindEvents() {
        document.querySelectorAll('[id^=note-btn]').forEach(button => {
            button.addEventListener('click', () => {
                this.toggleNotesRow(button.dataset.scenarioName);
            });
        });

        document.querySelectorAll('[id^=save-note]').forEach(button => {
            button.addEventListener('click', () => {
                this.saveNotes(button.dataset.scenarioName);
            });
        });
    },

    async toggleNotesRow(scenarioName) {
        const notesRow = document.getElementById(`notes-row-${scenarioName}`);
        const notesTextElement = document.getElementById(`notes-text-${scenarioName}`);

        if (notesRow.style.display === 'none') {
            try {
                const response = await fetch(`/platform/dashboard/${scenarioName}/notes`);
                const data = await response.json();

                if (data.status === 'success') {
                    notesTextElement.value = data.notes;
                } else {
                    notesTextElement.value = '';
                }
            } catch (error) {
                console.error('Error:', error);
                alert('An error occurred while retrieving the notes.');
                return;
            }
        }

        notesRow.style.display = notesRow.style.display === 'none' ? '' : 'none';
    },

    async saveNotes(scenarioName) {
        const notesText = document.getElementById(`notes-text-${scenarioName}`).value;

        try {
            const response = await fetch(`/platform/dashboard/${scenarioName}/save_note`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ notes: notesText }),
            });

            const data = await response.json();

            if (data.status === 'success') {
                showAlert('success', 'Notes saved successfully');
            } else {
                if (data.code === 401) {
                    showAlert('info', 'Some functionalities are disabled in the demo version.');
                } else {
                    showAlert('error', 'Failed to save notes');
                }
            }
        } catch (error) {
            console.error('Error:', error);
            showAlert('error', 'Failed to save notes');
        }
    }
};

export default NotesManager;
