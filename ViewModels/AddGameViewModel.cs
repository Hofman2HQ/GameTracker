using System;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Input;
using Microsoft.Maui.Controls;
using MyGameCatalog.Models;
using MyGameCatalog.Services.Interfaces;

namespace MyGameCatalog.ViewModels
{
    public class AddGameViewModel : INotifyPropertyChanged
    {
        private readonly IRAWGService _rawgService;
        private readonly ISQLiteService _sqliteService;
        public event PropertyChangedEventHandler PropertyChanged;

        public ObservableCollection<Game> Suggestions { get; set; } = new ObservableCollection<Game>();

        private string _searchQuery;
        public string SearchQuery
        {
            get => _searchQuery;
            set 
            {
                if (_searchQuery != value)
                {
                    _searchQuery = value;
                    OnPropertyChanged();
                    if (!string.IsNullOrWhiteSpace(_searchQuery) && _searchQuery.Length >= 3)
                    {
                        _ = SearchGamesAsync(_searchQuery);
                    }
                    else
                    {
                        Suggestions.Clear();
                    }
                }
            }
        }

        private Game _selectedGame;
        public Game SelectedGame
        {
            get => _selectedGame;
            set 
            {
                _selectedGame = value;
                OnPropertyChanged();
                ((Command)AddGameCommand).ChangeCanExecute();
            }
        }

        public ICommand AddGameCommand { get; }
        public ICommand SearchCommand { get; }

        private CancellationTokenSource _cts;

        public AddGameViewModel(IRAWGService rawgService, ISQLiteService sqliteService)
        {
            _rawgService = rawgService;
            _sqliteService = sqliteService;
            AddGameCommand = new Command(async () => await ExecuteAddGameCommand(), () => SelectedGame != null);
            SearchCommand = new Command<string>(async (query) => await SearchGamesAsync(query));
        }

        private async Task SearchGamesAsync(string query)
        {
            try
            {
                _cts?.Cancel();
                _cts = new CancellationTokenSource();
                var token = _cts.Token;
                await Task.Delay(300, token);  // Debounce delay.
                var results = await _rawgService.SearchGamesAsync(query);
                if (token.IsCancellationRequested)
                    return;
                Suggestions.Clear();
                foreach (var game in results)
                {
                    Suggestions.Add(game);
                }
            }
            catch (OperationCanceledException)
            {
                // Search was cancelled.
            }
            catch (Exception ex)
            {
                // Log or handle error.
            }
        }

        private async Task ExecuteAddGameCommand()
        {
            if (SelectedGame == null)
                return;

            // Check if the game already exists in local storage.
            var existingGame = await _sqliteService.Database.Table<Game>()
                                   .Where(g => g.GameId == SelectedGame.GameId)
                                   .FirstOrDefaultAsync();
            if (existingGame == null)
            {
                await _sqliteService.Database.InsertAsync(SelectedGame);
            }

            // For this MVP, we assume a fixed user (UserId = 1).
            var userCollection = new UserCollection
            {
                UserId = 1,
                GameId = SelectedGame.GameId,
                Status = "Backlog",
                Rating = null,
                Notes = string.Empty,
                DateAdded = DateTime.UtcNow
            };
            await _sqliteService.Database.InsertAsync(userCollection);
            await Application.Current.MainPage.DisplayAlert("Success", "Game added to your catalog.", "OK");
            await Application.Current.MainPage.Navigation.PopAsync();
        }

        protected void OnPropertyChanged([CallerMemberName] string propertyName = "") =>
           PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}