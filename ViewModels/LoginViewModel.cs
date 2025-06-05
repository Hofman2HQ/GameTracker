using System;
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
        private readonly ISecureStorage _secureStorage;
        public event PropertyChangedEventHandler PropertyChanged;

        private bool _isBusy;
        public bool IsBusy 
        {
            get => _isBusy;
            set 
            { 
                _isBusy = value; 
                OnPropertyChanged();
                ((Command)LoginCommand).ChangeCanExecute();
            }
        }

        private string _username;
        public string Username 
        {
            get => _username;
            set 
            { 
                _username = value; 
                OnPropertyChanged();
                ValidateInputs();
            }
        }

        private string _password;
        public string Password
        {
            get => _password;
            set 
            { 
                _password = value; 
                OnPropertyChanged();
                ValidateInputs();
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

        private bool _rememberMe;
        public bool RememberMe
        {
            get => _rememberMe;
            set
            {
                _rememberMe = value;
                OnPropertyChanged();
            }
        }

        public ICommand LoginCommand { get; }
        public ICommand GoogleLoginCommand { get; }

        public LoginViewModel(IAuthenticationService authService, ISecureStorage secureStorage)
        {
            _authService = authService ?? throw new ArgumentNullException(nameof(authService));
            _secureStorage = secureStorage ?? throw new ArgumentNullException(nameof(secureStorage));
            
            LoginCommand = new Command(async () => await ExecuteLoginCommand(), () => !IsBusy && IsInputValid());
            GoogleLoginCommand = new Command(async () => await ExecuteGoogleLoginCommand(), () => !IsBusy);

            // Load saved credentials if remember me was enabled
            _ = LoadSavedCredentialsAsync();
        }

        private async Task LoadSavedCredentialsAsync()
        {
            try
            {
                var savedUsername = await _secureStorage.GetAsync("saved_username");
                var savedRememberMe = await _secureStorage.GetAsync("remember_me");

                if (!string.IsNullOrEmpty(savedUsername) && savedRememberMe == "true")
                {
                    Username = savedUsername;
                    RememberMe = true;
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Failed to load saved credentials: {ex}");
            }
        }

        private async Task SaveCredentialsAsync()
        {
            try
            {
                if (RememberMe)
                {
                    await _secureStorage.SetAsync("saved_username", Username);
                    await _secureStorage.SetAsync("remember_me", "true");
                }
                else
                {
                    await _secureStorage.SetAsync("saved_username", null);
                    await _secureStorage.SetAsync("remember_me", "false");
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Failed to save credentials: {ex}");
            }
        }

        private bool IsInputValid()
        {
            return !string.IsNullOrWhiteSpace(Username) && 
                   !string.IsNullOrWhiteSpace(Password) && 
                   Password.Length >= 6;
        }

        private void ValidateInputs()
        {
            if (string.IsNullOrWhiteSpace(Username))
            {
                ErrorMessage = "Username is required";
            }
            else if (string.IsNullOrWhiteSpace(Password))
            {
                ErrorMessage = "Password is required";
            }
            else if (Password.Length < 6)
            {
                ErrorMessage = "Password must be at least 6 characters";
            }
            else
            {
                ErrorMessage = string.Empty;
            }

            ((Command)LoginCommand).ChangeCanExecute();
        }

        private async Task ExecuteLoginCommand()
        {
            if (IsBusy || !IsInputValid())
                return;

            IsBusy = true;
            ErrorMessage = string.Empty;

            try
            {
                var success = await _authService.LoginWithCredentialsAsync(Username, Password);
                if (success)
                {
                    await SaveCredentialsAsync();
                    await NavigateToMainPageAsync();
                }
                else
                {
                    ErrorMessage = "Invalid username or password";
                }
            }
            catch (Exception ex)
            {
                ErrorMessage = GetUserFriendlyErrorMessage(ex);
                System.Diagnostics.Debug.WriteLine($"Login error: {ex}");
            }
            finally
            {
                IsBusy = false;
            }
        }

        private async Task ExecuteGoogleLoginCommand()
        {
            if (IsBusy)
                return;

            IsBusy = true;
            ErrorMessage = string.Empty;

            try
            {
                var email = await _authService.LoginWithGoogleAsync();
                if (!string.IsNullOrEmpty(email))
                {
                    await NavigateToMainPageAsync();
                }
            }
            catch (Exception ex)
            {
                ErrorMessage = GetUserFriendlyErrorMessage(ex);
                System.Diagnostics.Debug.WriteLine($"Google login error: {ex}");
            }
            finally
            {
                IsBusy = false;
            }
        }

        private async Task NavigateToMainPageAsync()
        {
            try
            {
                var mainPage = (Page)App.Current.Services.GetService(typeof(Views.MainPage));
                if (mainPage != null)
                {
                    await Application.Current.MainPage.Navigation.PushAsync(mainPage);
                }
                else
                {
                    ErrorMessage = "Failed to navigate to main page";
                }
            }
            catch (Exception ex)
            {
                ErrorMessage = "Failed to navigate to main page";
                System.Diagnostics.Debug.WriteLine($"Navigation error: {ex}");
            }
        }

        private string GetUserFriendlyErrorMessage(Exception ex)
        {
            return ex switch
            {
                ApplicationException appEx => appEx.Message,
                HttpRequestException => "Network error. Please check your internet connection.",
                TaskCanceledException => "Login timed out. Please try again.",
                _ => "An unexpected error occurred. Please try again."
            };
        }

        protected void OnPropertyChanged([CallerMemberName] string propertyName = "") =>
           PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}
