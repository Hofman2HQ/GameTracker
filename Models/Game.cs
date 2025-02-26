using SQLite;

namespace MyGameCatalog.Models
{
    public class Game
    {
        [PrimaryKey]
        public int GameId { get; set; }
        public string Title { get; set; }
        public string CoverArtUrl { get; set; }
        public string Description { get; set; }
    }
}
