using System;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows.Input;
using Microsoft.Maui.Controls;
using MyGameCatalog.Models;
using MyGameCatalog.Services.Interfaces;
using System.Threading.Tasks;
using System.Linq;

namespace MyGameCatalog.ViewModels
{
    public class MainViewModel : INotifyPropertyChanged, IDisposable
    {
        private readonly ISQLiteService _sqliteService;
        private readonly IRAWGService _rawgService;
        private readonly IAuthenticationService _authService;
        private bool _disposed;
        private const int PageSize = 20;
        private int _currentPage = 0;
        private bool _hasMoreItems = true;

        public event PropertyChangedEventHandler PropertyChanged;

        public ObservableCollection<Game> Games { get; set; } = new ObservableCollection<Game>();

        private bool _isBusy;
        public bool IsBusy 
        {
            get => _isBusy;
            set 
            { 
                _isBusy = value; 
                OnPropertyChanged();
                ((Command)SearchCommand).ChangeCanExecute();
                ((Command)RefreshCommand).ChangeCanExecute();
                ((Command)LoadMoreCommand).ChangeCanExecute();
            }
        }

        private string _searchQuery;
        public string SearchQuery 
        {
            get => _searchQuery;
            set 
            { 
                _searchQuery = value; 
                OnPropertyChanged();
                ((Command)SearchCommand).ChangeCanExecute();
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

        private string _selectedFilter;
        public string SelectedFilter
        {
            get => _selectedFilter;
            set
            {
                _selectedFilter = value;
                OnPropertyChanged();
                _ = RefreshCollectionAsync();
            }
        }

        public ICommand SearchCommand { get; }
        public ICommand RefreshCommand { get; }
        public ICommand LoadMoreCommand { get; }

        public MainViewModel(
            ISQLiteService sqliteService, 
            IRAWGService rawgService,
            IAuthenticationService authService)
        {
            _sqliteService = sqliteService ?? throw new ArgumentNullException(nameof(sqliteService));
            _rawgService = rawgService ?? throw new ArgumentNullException(nameof(rawgService));
            _authService = authService ?? throw new ArgumentNullException(nameof(authService));

            SearchCommand = new Command(async () => await ExecuteSearchCommand(), () => !IsBusy && !string.IsNullOrWhiteSpace(SearchQuery));
            RefreshCommand = new Command(async () => await RefreshCollectionAsync(), () => !IsBusy);
            LoadMoreCommand = new Command(async () => await LoadMoreItemsAsync(), () => !IsBusy && _hasMoreItems);

            _ = InitializeAsync();
        }

        private async Task InitializeAsync()
        {
            try
            {
                await _sqliteService.InitializeAsync();
                await RefreshCollectionAsync();
            }
            catch (Exception ex)
            {
                ErrorMessage = "Failed to initialize the application";
                System.Diagnostics.Debug.WriteLine($"Initialization error: {ex}");
            }
        }

        private async Task ExecuteSearchCommand()
        {
            if (string.IsNullOrWhiteSpace(SearchQuery) || IsBusy)
                return;

            IsBusy = true;
            ErrorMessage = string.Empty;

            try
            {
                var games = await _rawgService.SearchGamesAsync(SearchQuery);
                Games.Clear();
                foreach (var game in games)
                {
                    Games.Add(game);
                }
            }
            catch (Exception ex)
            {
                ErrorMessage = "Failed to search games. Please try again.";
                System.Diagnostics.Debug.WriteLine($"Search error: {ex}");
            }
            finally
            {
                IsBusy = false;
            }
        }

        private async Task RefreshCollectionAsync()
        {
            if (IsBusy)
                return;

            IsBusy = true;
            ErrorMessage = string.Empty;
            _currentPage = 0;
            _hasMoreItems = true;

            try
            {
                await LoadUserCollectionAsync();
            }
            catch (Exception ex)
            {
                ErrorMessage = "Failed to refresh collection";
                System.Diagnostics.Debug.WriteLine($"Refresh error: {ex}");
            }
            finally
            {
                IsBusy = false;
            }
        }

        private async Task LoadMoreItemsAsync()
        {
            if (IsBusy || !_hasMoreItems)
                return;

            IsBusy = true;
            ErrorMessage = string.Empty;

            try
            {
                await LoadUserCollectionAsync(true);
            }
            catch (Exception ex)
            {
                ErrorMessage = "Failed to load more items";
                System.Diagnostics.Debug.WriteLine($"Load more error: {ex}");
            }
            finally
            {
                IsBusy = false;
            }
        }

        private async Task LoadUserCollectionAsync(bool append = false)
        {
            if (!_authService.IsAuthenticated)
            {
                ErrorMessage = "You must be logged in to view your collection";
                return;
            }

            try
            {
                var query = _sqliteService.Database.Table<Game>();
                
                // Apply filters if selected
                if (!string.IsNullOrEmpty(SelectedFilter))
                {
                    query = query.Where(g => g.Status == SelectedFilter);
                }

                // Apply pagination
                var games = await query
                    .Skip(_currentPage * PageSize)
                    .Take(PageSize)
                    .ToListAsync();

                if (!append)
                {
                    Games.Clear();
                }

                foreach (var game in games)
                {
                    Games.Add(game);
                }

                _hasMoreItems = games.Count == PageSize;
                _currentPage++;
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Load collection error: {ex}");
                throw;
            }
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
                    // Cleanup any resources
                    Games.Clear();
                }
                _disposed = true;
            }
        }
    }
}