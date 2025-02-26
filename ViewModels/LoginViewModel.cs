using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;
using System.Windows.Input;
using Microsoft.Maui.Controls;
using MyGameCatalog.Services.Interfaces;

namespace MyGameCatalog.ViewModels
{
    public class LoginViewModel : INotifyPropertyChanged
    {
        private readonly IAuthenticationService _authService;
        public event PropertyChangedEventHandler PropertyChanged;

        private bool _isBusy;
        public bool IsBusy 
        {
            get => _isBusy;
            set { _isBusy = value; OnPropertyChanged(); }
        }

        private string _userEmail;
        public string UserEmail 
        {
            get => _userEmail;
            set { _userEmail = value; OnPropertyChanged(); }
        }

        public ICommand LoginCommand { get; }

        public LoginViewModel(IAuthenticationService authService)
        {
            _authService = authService;
            LoginCommand = new Command(async () => await ExecuteLoginCommand());
        }

        private async Task ExecuteLoginCommand()
        {
            if (IsBusy)
                return;
            IsBusy = true;
            try
            {
                var email = await _authService.LoginWithGoogleAsync();
                UserEmail = email;
                // Navigate to MainPage (resolved from DI)
                await Application.Current.MainPage.Navigation.PushAsync(
                    (Page)App.Current.Services.GetService(typeof(Views.MainPage)));
            }
            catch (System.Exception ex)
            {
                // Log or display error.
            }
            finally
            {
                IsBusy = false;
            }
        }

        protected void OnPropertyChanged([CallerMemberName] string propertyName = "") =>
           PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}
