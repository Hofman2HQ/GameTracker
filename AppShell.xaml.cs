namespace MyGameCatalog
{
    public partial class AppShell : Shell
    {
        public AppShell()
        {
            InitializeComponent();

            Routing.RegisterRoute("Login", typeof(Views.LoginPage));
            Routing.RegisterRoute("Main", typeof(Views.MainPage));
            Routing.RegisterRoute("AddGame", typeof(Views.AddGamePage));
        }
    }
} 