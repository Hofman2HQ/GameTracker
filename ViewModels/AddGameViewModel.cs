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
    public class AddGameViewModel : INotifyPropertyChanged, IDisposable
    {
        private readonly IRAWGService _rawgService;
        private readonly ISQLiteService _sqliteService;
        private readonly IAuthenticationService _authService;
        private CancellationTokenSource _cts;
        private bool _disposed;

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

        private bool _isBusy;
        public bool IsBusy
        {
            get => _isBusy;
            set
            {
                _isBusy = value;
                OnPropertyChanged();
                ((Command)AddGameCommand).ChangeCanExecute();
            }
        }

        private string _errorMessage;
        public string ErrorMessage
        {
            get => _errorMessage;
            set
            {
                _errorMessage = value;
                OnPropertyChanged();
            }
        }

        public ICommand AddGameCommand { get; }
        public ICommand SearchCommand { get; }

        public AddGameViewModel(
            IRAWGService rawgService, 
            ISQLiteService sqliteService,
            IAuthenticationService authService)
        {
            _rawgService = rawgService ?? throw new ArgumentNullException(nameof(rawgService));
            _sqliteService = sqliteService ?? throw new ArgumentNullException(nameof(sqliteService));
            _authService = authService ?? throw new ArgumentNullException(nameof(authService));
            
            AddGameCommand = new Command(async () => await ExecuteAddGameCommand(), () => SelectedGame != null && !IsBusy);
            SearchCommand = new Command<string>(async (query) => await SearchGamesAsync(query));
        }

        private async Task SearchGamesAsync(string query)
        {
            if (string.IsNullOrWhiteSpace(query))
                return;

            try
            {
                _cts?.Cancel();
                _cts?.Dispose();
                _cts = new CancellationTokenSource();
                var token = _cts.Token;

                await Task.Delay(300, token);  // Debounce delay
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
                // Search was cancelled, no need to handle
            }
            catch (Exception ex)
            {
                ErrorMessage = "Failed to search games. Please try again.";
                System.Diagnostics.Debug.WriteLine($"Search error: {ex}");
            }
        }

        private async Task ExecuteAddGameCommand()
        {
            if (SelectedGame == null || IsBusy)
                return;

            IsBusy = true;
            ErrorMessage = string.Empty;

            try
            {
                if (!_authService.IsAuthenticated)
                {
                    ErrorMessage = "You must be logged in to add games.";
                    return;
                }

                // Validate game data
                if (string.IsNullOrWhiteSpace(SelectedGame.Title))
                {
                    ErrorMessage = "Invalid game data.";
                    return;
                }

                // Check if the game already exists in local storage
                var existingGame = await _sqliteService.Database.Table<Game>()
                                   .Where(g => g.GameId == SelectedGame.GameId)
                                   .FirstOrDefaultAsync();

                if (existingGame == null)
                {
                    await _sqliteService.Database.InsertAsync(SelectedGame);
                }

                // Get current user ID from authentication service
                var userId = await GetCurrentUserIdAsync();
                if (userId == 0)
                {
                    ErrorMessage = "Failed to get user information.";
                    return;
                }

                var userCollection = new UserCollection
                {
                    UserId = userId,
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
            catch (Exception ex)
            {
                ErrorMessage = "Failed to add game. Please try again.";
                System.Diagnostics.Debug.WriteLine($"Add game error: {ex}");
            }
            finally
            {
                IsBusy = false;
            }
        }

        private async Task<int> GetCurrentUserIdAsync()
        {
            // This should be implemented to get the actual user ID from the authentication service
            // For now, returning a placeholder
            return 1;
        }

        protected void OnPropertyChanged([CallerMemberName] string propertyName = "") =>
           PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));

        public void Dispose()
        {
            Dispose(true);
            GC.SuppressFinalize(this);
        }

        protected virtual void Dispose(bool disposing)
        {
            if (!_disposed)
            {
                if (disposing)
                {
                    _cts?.Dispose();
                }
                _disposed = true;
            }
        }
    }
}