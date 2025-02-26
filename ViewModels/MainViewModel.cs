using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows.Input;
using Microsoft.Maui.Controls;
using MyGameCatalog.Models;
using MyGameCatalog.Services.Interfaces;
using System.Threading.Tasks;

namespace MyGameCatalog.ViewModels
{
    public class MainViewModel : INotifyPropertyChanged
    {
        private readonly ISQLiteService _sqliteService;
        private readonly IRAWGService _rawgService;
        public event PropertyChangedEventHandler PropertyChanged;

        public ObservableCollection<Game> Games { get; set; } = new ObservableCollection<Game>();

        private bool _isBusy;
        public bool IsBusy 
        {
            get => _isBusy;
            set { _isBusy = value; OnPropertyChanged(); }
        }

        private string _searchQuery;
        public string SearchQuery 
        {
            get => _searchQuery;
            set { _searchQuery = value; OnPropertyChanged(); }
        }

        public ICommand SearchCommand { get; }

        public MainViewModel(ISQLiteService sqliteService, IRAWGService rawgService)
        {
            _sqliteService = sqliteService;
            _rawgService = rawgService;
            SearchCommand = new Command(async () => await ExecuteSearchCommand());
            LoadUserCollection();
        }

        private async Task ExecuteSearchCommand()
        {
            if (string.IsNullOrWhiteSpace(SearchQuery))
                return;

            IsBusy = true;
            try
            {
                // For demonstration, search RAWG API (this might be extended later).
                var games = await _rawgService.SearchGamesAsync(SearchQuery);
                Games.Clear();
                foreach (var game in games)
                {
                    Games.Add(game);
                }
            }
            catch (System.Exception ex)
            {
                // Handle error appropriately.
            }
            finally
            {
                IsBusy = false;
            }
        }

        private async void LoadUserCollection()
        {
            await _sqliteService.InitializeAsync();
            var userGames = await _sqliteService.Database.Table<Game>().ToListAsync();
            Games.Clear();
            foreach (var game in userGames)
            {
                Games.Add(game);
            }
        }

        protected void OnPropertyChanged([CallerMemberName] string propertyName = "") =>
           PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}